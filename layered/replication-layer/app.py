# layered/replication-layer/app.py
from flask import Flask, request, jsonify
import requests
import os
import logging
from collections import defaultdict
import hashlib

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_ACCESS_URL = os.getenv('DATA_ACCESS_URL', 'http://data-access:8082')
REGION = os.getenv('REGION', 'us-east')
PEER_URLS = os.getenv('PEER_URLS', '').split(',') if os.getenv('PEER_URLS') else []

# Vector clocks for tracking causality
vector_clocks = defaultdict(lambda: defaultdict(int))

def compute_hash(report):
    """Compute hash for quick comparison"""
    hash_str = f"{report['id']}{report['timestamp']}{report['version']}"
    return hashlib.md5(hash_str.encode()).hexdigest()

def last_write_wins(local_report, remote_report):
    """Last-Write-Wins conflict resolution strategy"""
    if remote_report['timestamp'] > local_report['timestamp']:
        logger.info(f"LWW: Remote version wins for {local_report['id']}")
        return remote_report, "remote"
    elif remote_report['timestamp'] < local_report['timestamp']:
        logger.info(f"LWW: Local version wins for {local_report['id']}")
        return local_report, "local"
    else:
        # Timestamp tie - use version as tiebreaker
        if remote_report['version'] > local_report['version']:
            return remote_report, "remote"
        else:
            return local_report, "local"

@app.route('/sync', methods=['POST'])
def sync_data():
    """
    FR5: Cross-Region Replication & Conflict Resolution
    Synchronize data from remote region
    """
    try:
        data = request.get_json()
        source_region = data.get('source_region')
        reports = data.get('reports', [])
        
        logger.info(f"Received sync from {source_region} with {len(reports)} reports")
        
        synced_ids = []
        conflicts = []
        
        for remote_report in reports:
            report_id = remote_report['id']
            
            try:
                # Check if report exists locally
                local_response = requests.get(
                    f'{DATA_ACCESS_URL}/reports/{report_id}',
                    timeout=5
                )
                
                if local_response.status_code == 200:
                    local_report = local_response.json()
                    
                    # Check if reports are identical
                    if compute_hash(local_report) == compute_hash(remote_report):
                        logger.info(f"Report {report_id} already in sync")
                        synced_ids.append(report_id)
                        continue
                    
                    # Conflict detected - resolve it
                    logger.warning(f"Conflict detected for report {report_id}")
                    
                    # Use Last-Write-Wins strategy
                    resolved_report, winner = last_write_wins(local_report, remote_report)
                    
                    # Update vector clock
                    vector_clocks[report_id][REGION] += 1
                    vector_clocks[report_id][source_region] = remote_report.get('vector_clock', {}).get(source_region, 0)
                    
                    # Update local database
                    update_response = requests.put(
                        f'{DATA_ACCESS_URL}/reports/{report_id}',
                        json=resolved_report,
                        timeout=10
                    )
                    
                    if update_response.status_code == 200:
                        synced_ids.append(report_id)
                        conflicts.append({
                            'report_id': report_id,
                            'resolution': winner,
                            'local_version': local_report['version'],
                            'remote_version': remote_report['version']
                        })
                
                elif local_response.status_code == 404:
                    # Report doesn't exist locally - create it
                    logger.info(f"Creating new report {report_id} from {source_region}")
                    
                    # Initialize vector clock
                    vector_clocks[report_id][source_region] = 1
                    
                    create_response = requests.post(
                        f'{DATA_ACCESS_URL}/reports',
                        json=remote_report,
                        timeout=10
                    )
                    
                    if create_response.status_code == 201:
                        synced_ids.append(report_id)
            
            except Exception as e:
                logger.error(f"Error syncing report {report_id}: {e}")
                continue
        
        return jsonify({
            'success': True,
            'synced_ids': synced_ids,
            'conflicts': conflicts,
            'region': REGION
        }), 200
    
    except Exception as e:
        logger.error(f"Error in sync_data: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/replicate', methods=['POST'])
def replicate_to_peers():
    """Replicate local changes to peer regions"""
    try:
        data = request.get_json()
        reports = data.get('reports', [])
        
        if not reports:
            return jsonify({'error': 'No reports provided'}), 400
        
        results = []
        
        for peer_url in PEER_URLS:
            if not peer_url:
                continue
            
            try:
                # Add vector clock information
                for report in reports:
                    report_id = report['id']
                    vector_clocks[report_id][REGION] += 1
                    report['vector_clock'] = dict(vector_clocks[report_id])
                
                response = requests.post(
                    f'{peer_url}/sync',
                    json={
                        'source_region': REGION,
                        'reports': reports
                    },
                    timeout=30
                )
                
                results.append({
                    'peer': peer_url,
                    'success': response.status_code == 200,
                    'response': response.json() if response.status_code == 200 else None
                })
                
                logger.info(f"Replicated {len(reports)} reports to {peer_url}")
                
            except Exception as e:
                logger.error(f"Failed to replicate to {peer_url}: {e}")
                results.append({
                    'peer': peer_url,
                    'success': False,
                    'error': str(e)
                })
        
        return jsonify({
            'success': True,
            'replication_results': results
        }), 200
    
    except Exception as e:
        logger.error(f"Error in replicate_to_peers: {e}")
        return jsonify({'error': 'Replication failed'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'service': 'replication-layer',
        'region': REGION,
        'peers': len([p for p in PEER_URLS if p])
    }), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8083))
    app.run(host='0.0.0.0', port=port, debug=False)