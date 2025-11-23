# layered/data-access-2pc/app.py
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import logging
import uuid
from contextlib import contextmanager
import grpc
import threading
import data_access_pb2 as two_pc_pb2
import data_access_pb2_grpc as two_pc_pb2_grpc
from concurrent import futures
import time

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'postgres-layered'),
    'port': 5432,
    'database': 'pet_reports',
    'user': 'petuser',
    'password': 'petpass'
}

###########################################################################
###########################################################################
# Replication Implementation Starts Here (Jennifer Hernandez)
REPLICA_ADDRESSES =  [a.strip() for a in os.getenv("DATA_ACCESS_REPLICAS", "").split(",") if a.strip()]
GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))
# Transaction tracks states per replica, gotta lock it to prevent race conditions on state
transactions = {}  # {transaction_id: {'state': 'INIT|PREPARED|COMMITTED|ABORTED'}}
transactions_lock = threading.Lock()
VOTE_TIMEOUT_SECONDS = int(os.getenv("VOTE_TIMEOUT", "5"))  

# gRPC Server implementation
class TwoPCServicer(two_pc_pb2_grpc.TwoPCServicer):
    def VoteRequest(self, request, context):            # replica received a VoteRequest
        transaction_id = request.transaction_id
        logger.info(f"VoteRequest received.")
        try:
            with get_db_connection() as conn:
                with conn.cursor() as cur:
                    # Simplified, always sends commit as long as db is reachable
                    with transactions_lock:
                        transactions[transaction_id] = {'state': 'PREPARED'}
            self_id_addr = os.getenv("SELF_ID", "unknown")
            logger.info(f"Phase Init of Node {self_id_addr} sends RPC VoteCommit to Phase Wait of Node data-access-1:50051")
            return two_pc_pb2.VoteResponse(vote=two_pc_pb2.VoteResponse.COMMIT)
        except Exception:       # couldnt reach DB or couldn't send Commit
            with transactions_lock:
                transactions[transaction_id] = {'state': 'ABORTED'}
            self_id_addr = os.getenv("SELF_ID", "unknown")
            logger.info(f"Phase Init of Node {self_id_addr} sends RPC VoteAbort to Phase Wait of Node data-access-1:50051")
            return two_pc_pb2.VoteResponse(vote=two_pc_pb2.VoteResponse.ABORT)

    def GlobalCommit(self, request, context):           # received GlobalCommit from coord
        transaction_id = request.transaction_id
        with transactions_lock:
            tx = transactions.get(transaction_id)
        logger.info(f"GlobalCommit Received")
        if tx and tx['state'] == 'PREPARED':            # send Ack if this GlobalCommit was valid
            tx['state'] = 'COMMITTED'
            self_id_addr = os.getenv("SELF_ID", "unknown")
            logger.info(f"Phase Ready of Node {self_id_addr} sends RPC Ack to Phase Commit of Node data-access-1:50051")
            return two_pc_pb2.Ack(success=True)
        return two_pc_pb2.Ack(success=False)

    def GlobalAbort(self, request, context):            # received GlobalAbort
        transaction_id = request.transaction_id
        logger.info(f"Received GlobalAbort")
        with transactions_lock:
            tx = transactions.get(transaction_id)
        if tx:                                          # send Ack if GlobalAbort was valid
            tx['state'] = 'ABORTED'
            self_id_addr = os.getenv("SELF_ID", "unknown")
            logger.info(f"Phase Ready of Node {self_id_addr} sends RPC Ack to Phase Abort of Node data-access-1:50051")
        return two_pc_pb2.Ack(success=True)

# Coordinator tasks
# Run the 2PC protocol: send VoteRequest to all replicas, if all COMMIT then GlobalCommit,
# otherwise GlobalAbort. Returns True if committed.
def run_2pc_coordinator(report):
    transaction_id = str(uuid.uuid4())
    logger.info(f"Coordinator starting transaction {transaction_id}")
    votes = []
    pb_report = two_pc_pb2.Report(      # convert from json to grpc report
        id=report.get('id', ''),
        type=report.get('type', ''),
        pet_type=report.get('pet_type', ''),
        breed=report.get('breed', ''),
        color=report.get('color', ''),
        latitude=report.get('location', {}).get('latitude', 0.0),
        longitude=report.get('location', {}).get('longitude', 0.0),
        address=report.get('location', {}).get('address', ''),
        timestamp=report.get('timestamp', 0),
        description=report.get('description', ''),
        photo_urls=report.get('photo_urls', []),
        contact_info=report.get('contact_info', ''),
        region=report.get('region', ''),
        version=report.get('version', 1)
    )
    for addr in REPLICA_ADDRESSES:          # send out vote requests to all data access replicas
        try:
            with grpc.insecure_channel(addr) as channel:
                stub = two_pc_pb2_grpc.TwoPCStub(channel)
                logger.info(f"Phase Init of Node data-access-1:50051 sends RPC VoteRequest to Phase Init of Node {addr}")
                vote = stub.VoteRequest(two_pc_pb2.ReportTransaction(transaction_id=transaction_id, report=pb_report))
                votes.append((addr, vote.vote))         # store votes received
                logger.info(f"Vote from {addr}: {vote.vote}")      
        except grpc.RpcError as e:          # no response means abort
            logger.error(f"{addr} unreachable: {e}")
            votes.append((addr, two_pc_pb2.VoteResponse.ABORT))
    if all(v == two_pc_pb2.VoteResponse.COMMIT for (a,v) in votes):     
        # if all replicas voted to commit, send GlobalCommit
        for addr in REPLICA_ADDRESSES:
            try: 
                with grpc.insecure_channel(addr) as channel:
                    stub = two_pc_pb2_grpc.TwoPCStub(channel)
                    logger.info(f"Phase Wait of Node data-access-1:50051 sends RPC GlobalCommit to Phase Ready of Node {addr}")
                    stub.GlobalCommit(two_pc_pb2.TransactionId(transaction_id=transaction_id), timeout=VOTE_TIMEOUT_SECONDS)
            except Exception as e:
                logger.error(f"failed to send GlobalCommit to {addr}: {e}")
        insert_report_db(report)
        logger.info(f"Transaction {transaction_id} Global Commit applied")
        return True
    else:
        # at least one replica voted to abort, send GlobalAbort to ones who committed
        for addr,v in votes:
            if v == two_pc_pb2.VoteResponse.COMMIT:
                try:
                    with grpc.insecure_channel(addr) as channel:
                        stub = two_pc_pb2_grpc.TwoPCStub(channel)
                        logger.info(f"Phase Wait of Node data-access-1:50051 sends RPC GlobalAbort to Phase Ready of Node {addr}")
                        stub.GlobalAbort(two_pc_pb2.TransactionId(transaction_id=transaction_id), timeout=VOTE_TIMEOUT_SECONDS)
                except Exception as e:
                    logger.error(f"failed to send GlobalAbort to {addr}")
        logger.info(f"Transaction {transaction_id} Global Abort applied")
        return False

# Wrap existing POST /reports
@app.route('/reports', methods=['POST'])
def create_report_2pc():
    if int(os.getenv("COORDINATOR", "0")):      # only coordinator node sends out to replicas
        data = request.get_json()
        success = run_2pc_coordinator(data)
        if success:     # print what was put in db
            return jsonify({'id': data.get('id', str(uuid.uuid4())), **data}), 201
        else:           # print error message
            return jsonify({'error': 'Transaction aborted'}), 500
    
def insert_report_db(report):
    # insert report into DB, returns report_id
    data = report
    report_id = data.get('id') or str(uuid.uuid4())     # generates a uuid if none provided
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO reports (
                    id, type, pet_type, breed, color,
                    latitude, longitude, address,
                    timestamp, description, photo_urls,
                    contact_info, region, version
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                report_id,
                data.get('type'),
                data.get('pet_type'),
                data.get('breed'),
                data.get('color'),
                data.get('location', {}).get('latitude'),
                data.get('location', {}).get('longitude'),
                data.get('location', {}).get('address'),
                data.get('timestamp'),
                data.get('description'),
                data.get('photo_urls', []),
                data.get('contact_info'),
                data.get('region'),
                data.get('version', 1)
            ))
    return report_id




def serve_grpc():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    two_pc_pb2_grpc.add_TwoPCServicer_to_server(TwoPCServicer(), server)
    grpc_host = f"[::]:{GRPC_PORT}"
    server.add_insecure_port(grpc_host)
    server.start()
    logger.info(f"gRPC TwoPC server started on port {GRPC_PORT}")
    # Keep the server running
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        server.stop(0)

############################################################################
############################################################################


@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    conn = None
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        yield conn
        conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        raise e
    finally:
        if conn:
            conn.close()

def init_database():
    """Initialize database schema"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Enable PostGIS extension
            cur.execute("CREATE EXTENSION IF NOT EXISTS postgis;")
            
            # Create reports table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id VARCHAR(36) PRIMARY KEY,
                    type VARCHAR(10) NOT NULL,
                    pet_type VARCHAR(50) NOT NULL,
                    breed VARCHAR(100),
                    color VARCHAR(50),
                    latitude DOUBLE PRECISION NOT NULL,
                    longitude DOUBLE PRECISION NOT NULL,
                    address TEXT,
                    timestamp BIGINT NOT NULL,
                    description TEXT,
                    photo_urls TEXT[],
                    contact_info VARCHAR(255),
                    region VARCHAR(50),
                    version BIGINT DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # Create spatial index
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_reports_location 
                ON reports USING GIST (ST_MakePoint(longitude, latitude));
            """)
            
            # Create other indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_reports_type ON reports(type);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_reports_timestamp ON reports(timestamp DESC);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_reports_region ON reports(region);")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_reports_pet_type ON reports(pet_type);")
            
            logger.info("Database initialized successfully")


# create report original route deleted here




@app.route('/reports/<report_id>', methods=['GET'])
def get_report(report_id):
    """Get a specific report"""
    try:
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT 
                        id, type, pet_type, breed, color,
                        latitude, longitude, address,
                        timestamp, description, photo_urls,
                        contact_info, region, version
                    FROM reports
                    WHERE id = %s
                """, (report_id,))
                
                row = cur.fetchone()
                
                if not row:
                    return jsonify({'error': 'Report not found'}), 404
                
                # Format response
                report = dict(row)
                report['location'] = {
                    'latitude': report.pop('latitude'),
                    'longitude': report.pop('longitude'),
                    'address': report.pop('address')
                }
                
                return jsonify(report), 200
    
    except Exception as e:
        logger.error(f"Error fetching report: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/reports/<report_id>', methods=['PUT'])
def update_report(report_id):
    """Update an existing report"""
    try:
        data = request.get_json()
        
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Increment version
                new_version = data.get('version', 1) + 1
                
                cur.execute("""
                    UPDATE reports
                    SET type = %s, pet_type = %s, breed = %s, color = %s,
                        latitude = %s, longitude = %s, address = %s,
                        timestamp = %s, description = %s, photo_urls = %s,
                        contact_info = %s, version = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (
                    data.get('type'),
                    data.get('pet_type'),
                    data.get('breed'),
                    data.get('color'),
                    data.get('location', {}).get('latitude'),
                    data.get('location', {}).get('longitude'),
                    data.get('location', {}).get('address'),
                    data.get('timestamp'),
                    data.get('description'),
                    data.get('photo_urls', []),
                    data.get('contact_info'),
                    new_version,
                    report_id
                ))
                
                if cur.rowcount == 0:
                    return jsonify({'error': 'Report not found'}), 404
        
        return jsonify({'success': True, 'version': new_version}), 200
    
    except Exception as e:
        logger.error(f"Error updating report: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/reports', methods=['GET'])
def list_reports():
    """List reports with filtering"""
    try:
        report_type = request.args.get('type', 'lost')
        limit = int(request.args.get('limit', 20))
        offset = int(request.args.get('offset', 0))
        
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Get reports
                cur.execute("""
                    SELECT 
                        id, type, pet_type, breed, color,
                        latitude, longitude, address,
                        timestamp, description, photo_urls,
                        contact_info, region, version
                    FROM reports
                    WHERE type = %s
                    ORDER BY timestamp DESC
                    LIMIT %s OFFSET %s
                """, (report_type, limit, offset))
                
                rows = cur.fetchall()
                
                # Format reports
                reports = []
                for row in rows:
                    report = dict(row)
                    report['location'] = {
                        'latitude': report.pop('latitude'),
                        'longitude': report.pop('longitude'),
                        'address': report.pop('address')
                    }
                    reports.append(report)
                
                # Get total count
                cur.execute("""
                    SELECT COUNT(*) as total
                    FROM reports
                    WHERE type = %s
                """, (report_type,))
                
                total = cur.fetchone()['total']
                
                return jsonify({
                    'reports': reports,
                    'total': total,
                    'limit': limit,
                    'offset': offset
                }), 200
    
    except Exception as e:
        logger.error(f"Error listing reports: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/search/nearby', methods=['POST'])
def nearby_search():
    """Search for nearby reports using PostGIS"""
    try:
        data = request.get_json()
        location = data.get('location', {})
        radius_km = data.get('radius_km', 10.0)
        report_type = data.get('type', 'lost')
        
        lat = location.get('latitude')
        lon = location.get('longitude')
        
        if not lat or not lon:
            return jsonify({'error': 'Location required'}), 400
        
        with get_db_connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Use PostGIS to find nearby reports
                # ST_DWithin uses meters for geography type
                cur.execute("""
                    SELECT 
                        id, type, pet_type, breed, color,
                        latitude, longitude, address,
                        timestamp, description, photo_urls,
                        contact_info, region, version,
                        ST_Distance(
                            ST_MakePoint(longitude, latitude)::geography,
                            ST_MakePoint(%s, %s)::geography
                        ) / 1000.0 as distance_km
                    FROM reports
                    WHERE type = %s
                        AND ST_DWithin(
                            ST_MakePoint(longitude, latitude)::geography,
                            ST_MakePoint(%s, %s)::geography,
                            %s
                        )
                    ORDER BY distance_km
                    LIMIT 50
                """, (lon, lat, report_type, lon, lat, radius_km * 1000))
                
                rows = cur.fetchall()
                
                # Format reports
                reports = []
                for row in rows:
                    report = dict(row)
                    distance = report.pop('distance_km')
                    report['location'] = {
                        'latitude': report.pop('latitude'),
                        'longitude': report.pop('longitude'),
                        'address': report.pop('address')
                    }
                    report['distance_km'] = round(distance, 2)
                    reports.append(report)
                
                return jsonify({
                    'reports': reports,
                    'count': len(reports),
                    'search_center': location,
                    'radius_km': radius_km
                }), 200
    
    except Exception as e:
        logger.error(f"Error in nearby search: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                return jsonify({
                    'status': 'healthy',
                    'service': 'data-access',
                    'database': 'connected'
                }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'service': 'data-access',
            'error': str(e)
        }), 503

if __name__ == '__main__':
    # Initialize database on startup
    try:
        init_database()
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
    
    # Start gRPC server in background thread
    t = threading.Thread(target=serve_grpc, daemon=True)
    t.start()
    # starts http interface
    port = int(os.getenv('PORT', 8082))
    app.run(host='0.0.0.0', port=port, debug=False)