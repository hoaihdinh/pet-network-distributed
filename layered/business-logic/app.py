# layered/business-logic/app.py
from flask import Flask, request, jsonify
import requests
import os
import logging
from datetime import datetime
import math

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATA_ACCESS_URL = os.getenv('DATA_ACCESS_URL', 'http://data-access:8082')
CACHE_URL = os.getenv('CACHE_URL', 'http://cache-layer:8084')

def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two coordinates using Haversine formula
    """
    R = 6371  # Earth's radius in km
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = math.sin(delta_lat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    
    return R * c

def calculate_match_score(report1, report2):
    """
    Calculate similarity score between two reports
    """
    score = 0.0
    max_score = 100.0
    
    # Pet type match (40 points)
    if report1.get('pet_type', '').lower() == report2.get('pet_type', '').lower():
        score += 40
    
    # Breed match (20 points)
    breed1 = report1.get('breed', '').lower()
    breed2 = report2.get('breed', '').lower()
    if breed1 and breed2 and breed1 == breed2:
        score += 20
    elif breed1 and breed2:
        # Partial match for similar breeds
        if breed1 in breed2 or breed2 in breed1:
            score += 10
    
    # Color match (20 points)
    color1 = report1.get('color', '').lower()
    color2 = report2.get('color', '').lower()
    if color1 and color2 and color1 == color2:
        score += 20
    elif color1 and color2:
        # Partial match for similar colors
        if color1 in color2 or color2 in color1:
            score += 10
    
    # Time proximity (20 points) - reports closer in time are more likely to match
    time1 = report1.get('timestamp', 0)
    time2 = report2.get('timestamp', 0)
    time_diff_days = abs(time1 - time2) / 86400  # Convert to days
    
    if time_diff_days <= 1:
        score += 20
    elif time_diff_days <= 3:
        score += 15
    elif time_diff_days <= 7:
        score += 10
    elif time_diff_days <= 14:
        score += 5
    
    return (score / max_score) * 100

@app.route('/reports', methods=['POST'])
def create_report():
    """
    Business logic for creating a report
    """
    try:
        data = request.get_json()
        
        # Add server-side timestamp
        data['timestamp'] = int(datetime.now().timestamp())
        data['version'] = 1
        data['region'] = os.getenv('REGION', 'us-east')
        
        # Validate business rules
        if data.get('type') not in ['lost', 'found']:
            return jsonify({'error': 'Type must be "lost" or "found"'}), 400
        
        location = data.get('location', {})
        if not (-90 <= location.get('latitude', 0) <= 90):
            return jsonify({'error': 'Invalid latitude'}), 400
        if not (-180 <= location.get('longitude', 0) <= 180):
            return jsonify({'error': 'Invalid longitude'}), 400
        
        # Store in data access layer
        response = requests.post(
            f'{DATA_ACCESS_URL}/reports',
            json=data,
            timeout=10
        )
        
        if response.status_code == 201:
            report = response.json()
            
            # Cache the report
            try:
                requests.post(
                    f'{CACHE_URL}/cache',
                    json={'key': f"report:{report['id']}", 'value': report},
                    timeout=5
                )
            except Exception as e:
                logger.warning(f"Cache update failed: {e}")
            
            # Index location for geo queries
            try:
                requests.post(
                    f'{CACHE_URL}/geo/index',
                    json={
                        'id': report['id'],
                        'location': report['location'],
                        'type': report['type']
                    },
                    timeout=5
                )
            except Exception as e:
                logger.warning(f"Geo indexing failed: {e}")
            
            return jsonify(report), 201
        
        return jsonify(response.json()), response.status_code
    
    except Exception as e:
        logger.error(f"Error in create_report: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/reports/<report_id>', methods=['GET'])
def get_report(report_id):
    """
    Get report with caching
    """
    try:
        # Try cache first
        try:
            cache_response = requests.get(
                f'{CACHE_URL}/cache/report:{report_id}',
                timeout=2
            )
            if cache_response.status_code == 200:
                logger.info(f"Cache hit for report {report_id}")
                return jsonify(cache_response.json()), 200
        except Exception as e:
            logger.warning(f"Cache miss: {e}")
        
        # Fetch from data layer
        response = requests.get(
            f'{DATA_ACCESS_URL}/reports/{report_id}',
            timeout=10
        )
        
        if response.status_code == 200:
            # Update cache
            try:
                requests.post(
                    f'{CACHE_URL}/cache',
                    json={'key': f"report:{report_id}", 'value': response.json()},
                    timeout=2
                )
            except Exception as e:
                logger.warning(f"Cache update failed: {e}")
        
        return jsonify(response.json()), response.status_code
    
    except Exception as e:
        logger.error(f"Error in get_report: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/reports', methods=['GET'])
def list_reports():
    """
    List reports with filtering
    """
    try:
        params = {
            'type': request.args.get('type', 'lost'),
            'limit': request.args.get('limit', 20, type=int),
            'offset': request.args.get('offset', 0, type=int)
        }
        
        response = requests.get(
            f'{DATA_ACCESS_URL}/reports',
            params=params,
            timeout=10
        )
        
        return jsonify(response.json()), response.status_code
    
    except Exception as e:
        logger.error(f"Error in list_reports: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/search/nearby', methods=['POST'])
def nearby_search():
    """
    Search for nearby reports using geo-indexed cache
    """
    try:
        data = request.get_json()
        location = data.get('location', {})
        radius_km = data.get('radius_km', 10.0)
        report_type = data.get('type', 'lost')
        
        # Query geo-indexed cache
        response = requests.post(
            f'{CACHE_URL}/geo/search',
            json={
                'location': location,
                'radius_km': radius_km,
                'type': report_type
            },
            timeout=10
        )
        
        if response.status_code == 200:
            return jsonify(response.json()), 200
        
        # Fallback to data layer if cache fails
        response = requests.post(
            f'{DATA_ACCESS_URL}/search/nearby',
            json=data,
            timeout=10
        )
        
        return jsonify(response.json()), response.status_code
    
    except Exception as e:
        logger.error(f"Error in nearby_search: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/matches/<report_id>', methods=['GET'])
def find_matches(report_id):
    """
    Find potential matches for a report (FR4: Distributed Match Query)
    """
    try:
        max_distance = request.args.get('max_distance', 50.0, type=float)
        limit = request.args.get('limit', 10, type=int)
        
        # Get the source report
        source_response = requests.get(
            f'{DATA_ACCESS_URL}/reports/{report_id}',
            timeout=10
        )
        
        if source_response.status_code != 200:
            return jsonify({'error': 'Report not found'}), 404
        
        source_report = source_response.json()
        
        # Determine opposite type (lost -> found, found -> lost)
        opposite_type = 'found' if source_report['type'] == 'lost' else 'lost'
        
        # Search for nearby reports of opposite type
        search_response = requests.post(
            f'{CACHE_URL}/geo/search',
            json={
                'location': source_report['location'],
                'radius_km': max_distance,
                'type': opposite_type
            },
            timeout=10
        )
        
        if search_response.status_code != 200:
            return jsonify({'matches': []}), 200
        
        nearby_reports = search_response.json().get('reports', [])
        
        # Calculate match scores
        matches = []
        for report in nearby_reports:
            # Calculate distance
            distance = calculate_distance(
                source_report['location']['latitude'],
                source_report['location']['longitude'],
                report['location']['latitude'],
                report['location']['longitude']
            )
            
            # Calculate match score
            score = calculate_match_score(source_report, report)
            
            matches.append({
                'report': report,
                'match_score': round(score, 2),
                'distance_km': round(distance, 2)
            })
        
        # Sort by match score (descending)
        matches.sort(key=lambda x: x['match_score'], reverse=True)
        
        # Limit results
        matches = matches[:limit]
        
        return jsonify({'matches': matches}), 200
    
    except Exception as e:
        logger.error(f"Error in find_matches: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/alerts/subscribe', methods=['POST'])
def subscribe_alerts():
    """
    Subscribe to geo-based alerts
    """
    try:
        data = request.get_json()
        
        # Forward to cache layer which manages subscriptions
        response = requests.post(
            f'{CACHE_URL}/alerts/subscribe',
            json=data,
            timeout=10
        )
        
        return jsonify(response.json()), response.status_code
    
    except Exception as e:
        logger.error(f"Error in subscribe_alerts: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/alerts/unsubscribe', methods=['POST'])
def unsubscribe_alerts():
    """
    Unsubscribe from alerts
    """
    try:
        data = request.get_json()
        
        response = requests.post(
            f'{CACHE_URL}/alerts/unsubscribe',
            json=data,
            timeout=10
        )
        
        return jsonify(response.json()), response.status_code
    
    except Exception as e:
        logger.error(f"Error in unsubscribe_alerts: {e}")
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'healthy', 'service': 'business-logic'}), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8081))
    app.run(host='0.0.0.0', port=port, debug=False)