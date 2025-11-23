# layered/data-access/app.py
from flask import Flask, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor
import os
import logging
import uuid
from contextlib import contextmanager

import threading
import asyncio
import simple_raft

# Flask configuration 
app = Flask(__name__)

def run_flask_app():
    port = int(os.getenv('PORT', 8082))
    app.run(host='0.0.0.0', port=port, debug=False)

# Logger configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Database configuration
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'postgres-layered'),
    'port': 5432,
    'database': 'pet_reports',
    'user': 'petuser',
    'password': 'petpass'
}

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

# Raft Node configuration
async def create_report_task(query: str) -> int:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
    return 201

async def update_report_task(query: str) -> int:
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query)
            if cur.rowcount == 0:
                return 404
    return 200

raft_loop = asyncio.new_event_loop()

raft_node = simple_raft.RaftNode(
    node_id=int(os.getenv("NODE_ID")),
    port=int(os.getenv("GRPC_PORT")),
    peers=os.getenv("PEERS").split(","),
    op_to_function_map={
        "[LEADER]|CREATE_REPORT": create_report_task,
        "[LEADER]|UPDATE_REPORT": update_report_task,
    }
)

async def run_raft_node():
    try:
        await raft_node.start()
    except Exception as e:
        logger.error(f"Raft server crashed: {e}")

# Flask endpoints
@app.route('/reports', methods=['POST'])
def create_report():
    """Create a new report"""
    try:
        data = request.get_json()

        # Generate ID if not provided
        report_id = data.get('id', str(uuid.uuid4()))
        
        # Construct the operation to be submitted to Raft
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                query = cur.mogrify("""
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
                )).decode('utf-8')

        status_code = asyncio.run_coroutine_threadsafe(
            raft_node.submit_client_command("[LEADER]|CREATE_REPORT", query),
            raft_loop
        ).result()

        # Return created report
        return jsonify({
            'id': report_id,
            **data
        }), status_code
    
    except Exception as e:
        logger.error(f"Error creating report: {e}")
        return jsonify({'error': str(e)}), 500

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
        
        # Construct the operation to be submitted to Raft
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                # Increment version
                new_version = data.get('version', 1) + 1
                
                query = cur.mogrify("""
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
                )).decode('utf-8')
        
        status_code = asyncio.run_coroutine_threadsafe(
            raft_node.submit_client_command("[LEADER]|UPDATE_REPORT", query),
            raft_loop
        ).result()

        if status_code == 500:
            raise Exception("Failed to update report via Raft")
        elif status_code == 404:
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

    # Run Flask in a seperate thread because its server is blocking, which would
    # prevent the asyncio event loop (used by the simple_raft.RaftNode) from running.
    flask_thread = threading.Thread(
        target=run_flask_app,
        daemon=True # Once the main program ends, then the Flask thread will also end
    )
    flask_thread.start()

    asyncio.set_event_loop(raft_loop)
    raft_loop.run_until_complete(run_raft_node())
    