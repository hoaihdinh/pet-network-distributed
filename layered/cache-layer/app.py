# layered/cache-layer/app.py
from flask import Flask, request, jsonify
import redis
import json
import os
import logging
import time

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

REDIS_HOST = os.getenv('REDIS_HOST', 'redis-layered')
REDIS_PORT = 6379
CACHE_TTL = 3600  # 1 hour

# Initialize Redis
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True
)

# ========== BASIC CACHING ==========

@app.route('/cache', methods=['POST'])
def set_cache():
    """Set a key-value pair in cache"""
    try:
        data = request.get_json()
        key = data.get('key')
        value = data.get('value')
        ttl = data.get('ttl', CACHE_TTL)
        
        if not key:
            return jsonify({'error': 'Key is required'}), 400
        
        # Serialize value
        serialized = json.dumps(value) if isinstance(value, dict) else str(value)
        redis_client.setex(key, ttl, serialized)
        
        logger.info(f"Cached key: {key}")
        return jsonify({'success': True, 'key': key}), 200
    
    except Exception as e:
        logger.error(f"Error setting cache: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/cache/<key>', methods=['GET'])
def get_cache(key):
    """Get a value from cache"""
    try:
        value = redis_client.get(key)
        
        if not value:
            return jsonify({'error': 'Key not found'}), 404
        
        # Try to deserialize as JSON
        try:
            data = json.loads(value)
        except:
            data = value
        
        return jsonify(data), 200
    
    except Exception as e:
        logger.error(f"Error getting cache: {e}")
        return jsonify({'error': str(e)}), 500

# ========== GEOSPATIAL INDEXING (FR2) ==========

@app.route('/geo/index', methods=['POST'])
def index_location():
    """
    FR2: Index a report's location for fast nearby search
    """
    try:
        data = request.get_json()
        report_id = data.get('id')
        location = data.get('location', {})
        report_type = data.get('type', 'lost')
        
        lat = location.get('latitude')
        lon = location.get('longitude')
        
        if not all([report_id, lat, lon]):
            return jsonify({'error': 'ID and location required'}), 400
        
        # Use separate geo indexes for lost and found
        geo_key = f"geo:{report_type}"
        
        # Add to Redis GEO index (lon, lat order!)
        redis_client.geoadd(geo_key, (lon, lat, report_id))
        
        # Store full report data for quick retrieval
        redis_client.setex(
            f"geo_report:{report_id}",
            CACHE_TTL,
            json.dumps(data)
        )
        
        logger.info(f"Indexed location for {report_id}")
        return jsonify({'success': True}), 200
    
    except Exception as e:
        logger.error(f"Error indexing location: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/geo/search', methods=['POST'])
def geo_search():
    """
    FR2: Search for reports within radius using Redis GEORADIUS
    """
    try:
        data = request.get_json()
        location = data.get('location', {})
        radius_km = data.get('radius_km', 10.0)
        report_type = data.get('type', 'lost')
        
        lat = location.get('latitude')
        lon = location.get('longitude')
        
        if not lat or not lon:
            return jsonify({'error': 'Location required'}), 400
        
        geo_key = f"geo:{report_type}"
        
        # GEORADIUS: find reports within radius
        results = redis_client.georadius(
            geo_key,
            lon,
            lat,
            radius_km,
            unit='km',
            withdist=True,
            sort='ASC',
            count=50
        )
        
        # Fetch full report data
        reports = []
        for report_id, distance in results:
            report_data = redis_client.get(f"geo_report:{report_id}")
            if report_data:
                report = json.loads(report_data)
                report['distance_km'] = round(float(distance), 2)
                reports.append(report)
        
        logger.info(f"Found {len(reports)} reports within {radius_km}km")
        return jsonify({
            'reports': reports,
            'count': len(reports),
            'search_center': location,
            'radius_km': radius_km
        }), 200
    
    except Exception as e:
        logger.error(f"Error in geo search: {e}")
        return jsonify({'error': str(e)}), 500

# ========== REAL-TIME ALERTS (FR3) ==========

@app.route('/alerts/subscribe', methods=['POST'])
def subscribe_alerts():
    """
    FR3: Subscribe to real-time alerts for a geographic area
    """
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        location = data.get('location', {})
        radius_km = data.get('radius_km', 10.0)
        pet_types = data.get('pet_types', [])
        
        if not user_id or not location:
            return jsonify({'error': 'User ID and location required'}), 400
        
        # Generate subscription ID
        subscription_id = f"{user_id}:{int(time.time())}"
        
        # Store subscription details
        subscription_data = {
            'subscription_id': subscription_id,
            'user_id': user_id,
            'location': location,
            'radius_km': radius_km,
            'pet_types': pet_types,
            'created_at': int(time.time())
        }
        
        # Store in Redis (expires in 24 hours)
        redis_client.setex(
            f"subscription:{subscription_id}",
            86400,
            json.dumps(subscription_data)
        )
        
        # Add to user's subscription list
        redis_client.sadd(f"user_subscriptions:{user_id}", subscription_id)
        
        # Index subscription location for proximity matching
        redis_client.geoadd(
            "subscription_locations",
            (location['longitude'], location['latitude'], subscription_id)
        )
        
        logger.info(f"Created subscription {subscription_id} for {user_id}")
        
        return jsonify({
            'success': True,
            'subscription_id': subscription_id,
            'message': 'Subscription created successfully'
        }), 201
    
    except Exception as e:
        logger.error(f"Error creating subscription: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/alerts/unsubscribe', methods=['POST'])
def unsubscribe_alerts():
    """Unsubscribe from alerts"""
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        subscription_id = data.get('subscription_id')
        
        if not user_id or not subscription_id:
            return jsonify({'error': 'User ID and subscription ID required'}), 400
        
        # Remove subscription
        redis_client.delete(f"subscription:{subscription_id}")
        redis_client.srem(f"user_subscriptions:{user_id}", subscription_id)
        redis_client.zrem("subscription_locations", subscription_id)
        
        logger.info(f"Removed subscription {subscription_id}")
        
        return jsonify({'success': True}), 200
    
    except Exception as e:
        logger.error(f"Error removing subscription: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/alerts/publish', methods=['POST'])
def publish_alert():
    """
    FR3: Publish alert when new report is created
    Find matching subscriptions and notify users
    """
    try:
        data = request.get_json()
        report = data.get('report', {})
        
        if not report or not report.get('location'):
            return jsonify({'error': 'Report with location required'}), 400
        
        location = report['location']
        pet_type = report.get('pet_type')
        
        # Find nearby subscriptions (within 50km to catch all)
        nearby_subscriptions = redis_client.georadius(
            "subscription_locations",
            location['longitude'],
            location['latitude'],
            50,
            unit='km',
            withdist=True
        )
        
        notified_users = []
        
        for subscription_id, distance in nearby_subscriptions:
            # Get subscription details
            sub_data = redis_client.get(f"subscription:{subscription_id}")
            if not sub_data:
                continue
            
            subscription = json.loads(sub_data)
            
            # Check if report matches subscription criteria
            if distance <= subscription['radius_km']:
                # Check pet type filter
                if subscription.get('pet_types') and pet_type not in subscription['pet_types']:
                    continue
                
                # Create alert
                alert = {
                    'subscription_id': subscription_id,
                    'user_id': subscription['user_id'],
                    'report': report,
                    'distance_km': round(float(distance), 2),
                    'timestamp': int(time.time())
                }
                
                # Store alert
                alert_key = f"alert:{subscription['user_id']}:{int(time.time())}"
                redis_client.setex(alert_key, 86400, json.dumps(alert))
                
                # Add to user's alert list (keep last 100)
                redis_client.lpush(f"user_alerts:{subscription['user_id']}", alert_key)
                redis_client.ltrim(f"user_alerts:{subscription['user_id']}", 0, 99)
                
                notified_users.append(subscription['user_id'])
        
        logger.info(f"Published alert to {len(notified_users)} users")
        
        return jsonify({
            'success': True,
            'notified_users': len(notified_users),
            'user_ids': notified_users
        }), 200
    
    except Exception as e:
        logger.error(f"Error publishing alert: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/alerts/<user_id>', methods=['GET'])
def get_user_alerts(user_id):
    """Get recent alerts for a user"""
    try:
        limit = int(request.args.get('limit', 10))
        
        # Get alert keys
        alert_keys = redis_client.lrange(f"user_alerts:{user_id}", 0, limit - 1)
        
        # Fetch alert data
        alerts = []
        for key in alert_keys:
            alert_data = redis_client.get(key)
            if alert_data:
                alerts.append(json.loads(alert_data))
        
        return jsonify({
            'alerts': alerts,
            'count': len(alerts)
        }), 200
    
    except Exception as e:
        logger.error(f"Error getting alerts: {e}")
        return jsonify({'error': str(e)}), 500

# ========== STATISTICS ==========

@app.route('/stats', methods=['GET'])
def get_stats():
    """Get cache statistics"""
    try:
        info = redis_client.info('stats')
        
        # Count geo-indexed reports
        lost_count = redis_client.zcard('geo:lost')
        found_count = redis_client.zcard('geo:found')
        
        # Count subscriptions
        subscription_count = redis_client.zcard('subscription_locations')
        
        return jsonify({
            'cache_hits': info.get('keyspace_hits', 0),
            'cache_misses': info.get('keyspace_misses', 0),
            'geo_indexed_lost': lost_count,
            'geo_indexed_found': found_count,
            'active_subscriptions': subscription_count,
            'total_keys': redis_client.dbsize()
        }), 200
    
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check"""
    try:
        redis_client.ping()
        return jsonify({
            'status': 'healthy',
            'service': 'cache-layer',
            'redis': 'connected'
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'service': 'cache-layer',
            'error': str(e)
        }), 503

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8084))
    app.run(host='0.0.0.0', port=port, debug=False)