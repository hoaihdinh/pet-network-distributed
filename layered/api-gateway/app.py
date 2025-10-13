# layered/api-gateway/app.py
from flask import Flask, request, jsonify
import requests
import os
import logging

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BUSINESS_LOGIC_URL = os.getenv('BUSINESS_LOGIC_URL', 'http://business-logic:8081')

# FR1: Create Lost/Found Report
@app.route('/api/reports', methods=['POST'])
def create_report():
    """
    Create a new lost or found pet report
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['type', 'pet_type', 'location']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Forward to business logic layer
        response = requests.post(
            f'{BUSINESS_LOGIC_URL}/reports',
            json=data,
            timeout=10
        )
        
        return jsonify(response.json()), response.status_code
    
    except requests.RequestException as e:
        logger.error(f"Error connecting to business logic: {e}")
        return jsonify({'error': 'Service unavailable'}), 503
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/api/reports/<report_id>', methods=['GET'])
def get_report(report_id):
    """
    Retrieve a specific report by ID
    """
    try:
        response = requests.get(
            f'{BUSINESS_LOGIC_URL}/reports/{report_id}',
            timeout=10
        )
        return jsonify(response.json()), response.status_code
    
    except requests.RequestException as e:
        logger.error(f"Error connecting to business logic: {e}")
        return jsonify({'error': 'Service unavailable'}), 503

@app.route('/api/reports', methods=['GET'])
def list_reports():
    """
    List reports with filtering
    """
    try:
        # Extract query parameters
        report_type = request.args.get('type', 'lost')
        limit = request.args.get('limit', 20, type=int)
        offset = request.args.get('offset', 0, type=int)
        
        params = {
            'type': report_type,
            'limit': limit,
            'offset': offset
        }
        
        response = requests.get(
            f'{BUSINESS_LOGIC_URL}/reports',
            params=params,
            timeout=10
        )
        
        return jsonify(response.json()), response.status_code
    
    except requests.RequestException as e:
        logger.error(f"Error connecting to business logic: {e}")
        return jsonify({'error': 'Service unavailable'}), 503

# FR2: Nearby Match Search
@app.route('/api/search/nearby', methods=['POST'])
def nearby_search():
    """
    Search for reports near a specific location
    """
    try:
        data = request.get_json()
        
        if 'location' not in data:
            return jsonify({'error': 'Location is required'}), 400
        
        response = requests.post(
            f'{BUSINESS_LOGIC_URL}/search/nearby',
            json=data,
            timeout=10
        )
        
        return jsonify(response.json()), response.status_code
    
    except requests.RequestException as e:
        logger.error(f"Error connecting to business logic: {e}")
        return jsonify({'error': 'Service unavailable'}), 503

# FR4: Distributed Match Query
@app.route('/api/matches/<report_id>', methods=['GET'])
def find_matches(report_id):
    """
    Find potential matches for a report
    """
    try:
        max_distance = request.args.get('max_distance', 50.0, type=float)
        limit = request.args.get('limit', 10, type=int)
        
        params = {
            'max_distance': max_distance,
            'limit': limit
        }
        
        response = requests.get(
            f'{BUSINESS_LOGIC_URL}/matches/{report_id}',
            params=params,
            timeout=15
        )
        
        return jsonify(response.json()), response.status_code
    
    except requests.RequestException as e:
        logger.error(f"Error connecting to business logic: {e}")
        return jsonify({'error': 'Service unavailable'}), 503

# FR3: Real-Time Geo Alerts (Subscription Management)
@app.route('/api/alerts/subscribe', methods=['POST'])
def subscribe_alerts():
    """
    Subscribe to real-time alerts for a geographic area
    """
    try:
        data = request.get_json()
        
        required_fields = ['user_id', 'location', 'radius_km']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        response = requests.post(
            f'{BUSINESS_LOGIC_URL}/alerts/subscribe',
            json=data,
            timeout=10
        )
        
        return jsonify(response.json()), response.status_code
    
    except requests.RequestException as e:
        logger.error(f"Error connecting to business logic: {e}")
        return jsonify({'error': 'Service unavailable'}), 503

@app.route('/api/alerts/unsubscribe', methods=['POST'])
def unsubscribe_alerts():
    """
    Unsubscribe from alerts
    """
    try:
        data = request.get_json()
        
        response = requests.post(
            f'{BUSINESS_LOGIC_URL}/alerts/unsubscribe',
            json=data,
            timeout=10
        )
        
        return jsonify(response.json()), response.status_code
    
    except requests.RequestException as e:
        logger.error(f"Error connecting to business logic: {e}")
        return jsonify({'error': 'Service unavailable'}), 503

# Health check
@app.route('/health', methods=['GET'])
def health_check():
    """
    Health check endpoint
    """
    try:
        # Check connection to business logic layer
        response = requests.get(
            f'{BUSINESS_LOGIC_URL}/health',
            timeout=5
        )
        
        return jsonify({
            'status': 'healthy',
            'service': 'api-gateway',
            'business_logic': 'connected' if response.status_code == 200 else 'disconnected'
        }), 200
    
    except Exception as e:
        return jsonify({
            'status': 'degraded',
            'service': 'api-gateway',
            'error': str(e)
        }), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False)
            