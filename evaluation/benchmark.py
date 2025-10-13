# evaluation/benchmark.py
import requests
import time
import json
import random
import statistics
import concurrent.futures
from datetime import datetime
import matplotlib.pyplot as plt

# Configuration
MICROSERVICES_BASE_URL = "http://localhost:50051"
LAYERED_BASE_URL = "http://localhost:8080"

# Test data generators
def generate_location():
    """Generate random location within reasonable bounds"""
    return {
        "latitude": random.uniform(25.0, 48.0),  # US latitude range
        "longitude": random.uniform(-125.0, -65.0),  # US longitude range
        "address": f"{random.randint(1, 9999)} Test St"
    }

def generate_report():
    """Generate random pet report"""
    pet_types = ["dog", "cat", "bird", "rabbit"]
    breeds = {
        "dog": ["labrador", "poodle", "beagle", "bulldog"],
        "cat": ["siamese", "persian", "maine coon", "ragdoll"],
        "bird": ["parrot", "cockatiel", "canary", "finch"],
        "rabbit": ["holland lop", "lionhead", "flemish giant", "rex"]
    }
    colors = ["brown", "black", "white", "gray", "orange", "mixed"]
    
    pet_type = random.choice(pet_types)
    
    return {
        "type": random.choice(["lost", "found"]),
        "pet_type": pet_type,
        "breed": random.choice(breeds[pet_type]),
        "color": random.choice(colors),
        "location": generate_location(),
        "description": f"Test pet description {random.randint(1000, 9999)}",
        "photo_urls": [f"https://example.com/photo{i}.jpg" for i in range(random.randint(1, 3))],
        "contact_info": f"test{random.randint(1000, 9999)}@example.com"
    }

class PerformanceMetrics:
    """Track and calculate performance metrics"""
    def __init__(self):
        self.latencies = []
        self.errors = 0
        self.successes = 0
        self.start_time = None
        self.end_time = None
    
    def add_result(self, latency, success=True):
        if success:
            self.latencies.append(latency)
            self.successes += 1
        else:
            self.errors += 1
    
    def get_metrics(self):
        if not self.latencies:
            return {
                "avg_latency_ms": 0,
                "p50_latency_ms": 0,
                "p95_latency_ms": 0,
                "p99_latency_ms": 0,
                "min_latency_ms": 0,
                "max_latency_ms": 0,
                "throughput_rps": 0,
                "success_rate": 0,
                "total_requests": self.successes + self.errors
            }
        
        duration = (self.end_time - self.start_time) if self.end_time and self.start_time else 1
        
        return {
            "avg_latency_ms": statistics.mean(self.latencies),
            "p50_latency_ms": statistics.median(self.latencies),
            "p95_latency_ms": statistics.quantiles(self.latencies, n=20)[18] if len(self.latencies) > 1 else self.latencies[0],
            "p99_latency_ms": statistics.quantiles(self.latencies, n=100)[98] if len(self.latencies) > 1 else self.latencies[0],
            "min_latency_ms": min(self.latencies),
            "max_latency_ms": max(self.latencies),
            "throughput_rps": self.successes / duration,
            "success_rate": (self.successes / (self.successes + self.errors)) * 100 if (self.successes + self.errors) > 0 else 0,
            "total_requests": self.successes + self.errors
        }

def test_create_report_rest(base_url, report_data):
    """Test report creation via REST API"""
    start = time.time()
    try:
        response = requests.post(
            f"{base_url}/api/reports",
            json=report_data,
            timeout=30
        )
        latency = (time.time() - start) * 1000  # Convert to ms
        return latency, response.status_code == 201, response.json() if response.status_code == 201 else None
    except Exception as e:
        latency = (time.time() - start) * 1000
        return latency, False, None

def test_nearby_search_rest(base_url, location, radius_km=10):
    """Test nearby search via REST API"""
    start = time.time()
    try:
        response = requests.post(
            f"{base_url}/api/search/nearby",
            json={
                "location": location,
                "radius_km": radius_km,
                "type": "lost"
            },
            timeout=30
        )
        latency = (time.time() - start) * 1000
        return latency, response.status_code == 200
    except Exception as e:
        latency = (time.time() - start) * 1000
        return latency, False

def test_find_matches_rest(base_url, report_id):
    """Test match finding via REST API"""
    start = time.time()
    try:
        response = requests.get(
            f"{base_url}/api/matches/{report_id}",
            params={"max_distance": 50, "limit": 10},
            timeout=30
        )
        latency = (time.time() - start) * 1000
        return latency, response.status_code == 200
    except Exception as e:
        latency = (time.time() - start) * 1000
        return latency, False

def run_workload_test(base_url, architecture_name, num_requests=100, concurrent_users=10):
    """
    Run a comprehensive workload test
    """
    print(f"\n{'='*60}")
    print(f"Testing {architecture_name} Architecture")
    print(f"Requests: {num_requests}, Concurrent Users: {concurrent_users}")
    print(f"{'='*60}\n")
    
    # Metrics for different operations
    create_metrics = PerformanceMetrics()
    search_metrics = PerformanceMetrics()
    match_metrics = PerformanceMetrics()
    
    # Phase 1: Create reports
    print(f"Phase 1: Creating {num_requests} reports...")
    create_metrics.start_time = time.time()
    
    created_report_ids = []
    
    def create_report_task(i):
        report_data = generate_report()
        latency, success, response = test_create_report_rest(base_url, report_data)
        create_metrics.add_result(latency, success)
        if success and response:
            return response.get('id')
        return None
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_users) as executor:
        futures = [executor.submit(create_report_task, i) for i in range(num_requests)]
        for future in concurrent.futures.as_completed(futures):
            report_id = future.result()
            if report_id:
                created_report_ids.append(report_id)
    
    create_metrics.end_time = time.time()
    
    print(f"Created {len(created_report_ids)} reports")
    print(f"Create Report Metrics:")
    for key, value in create_metrics.get_metrics().items():
        print(f"  {key}: {value:.2f}")
    
    # Wait a bit for indexing
    time.sleep(2)
    
    # Phase 2: Nearby searches
    print(f"\nPhase 2: Running {num_requests // 2} nearby searches...")
    search_metrics.start_time = time.time()
    
    def search_task(i):
        location = generate_location()
        latency, success = test_nearby_search_rest(base_url, location, radius_km=random.uniform(5, 50))
        search_metrics.add_result(latency, success)
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_users) as executor:
        futures = [executor.submit(search_task, i) for i in range(num_requests // 2)]
        concurrent.futures.wait(futures)
    
    search_metrics.end_time = time.time()
    
    print(f"Nearby Search Metrics:")
    for key, value in search_metrics.get_metrics().items():
        print(f"  {key}: {value:.2f}")
    
    # Phase 3: Match queries
    if created_report_ids:
        print(f"\nPhase 3: Running {min(len(created_report_ids), num_requests // 2)} match queries...")
        match_metrics.start_time = time.time()
        
        def match_task(report_id):
            latency, success = test_find_matches_rest(base_url, report_id)
            match_metrics.add_result(latency, success)
        
        sample_ids = random.sample(created_report_ids, min(len(created_report_ids), num_requests // 2))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_users) as executor:
            futures = [executor.submit(match_task, rid) for rid in sample_ids]
            concurrent.futures.wait(futures)
        
        match_metrics.end_time = time.time()
        
        print(f"Match Query Metrics:")
        for key, value in match_metrics.get_metrics().items():
            print(f"  {key}: {value:.2f}")
    
    return {
        "architecture": architecture_name,
        "create": create_metrics.get_metrics(),
        "search": search_metrics.get_metrics(),
        "match": match_metrics.get_metrics()
    }

def compare_architectures(results):
    """
    Generate comparison charts and summary
    """
    print(f"\n{'='*60}")
    print("ARCHITECTURE COMPARISON")
    print(f"{'='*60}\n")
    
    # Comparison table
    print(f"{'Operation':<20} {'Metric':<20} {'Microservices':<15} {'Layered':<15}")
    print("-" * 70)
    
    operations = ["create", "search", "match"]
    metrics = ["avg_latency_ms", "p95_latency_ms", "throughput_rps"]
    
    for op in operations:
        for metric in metrics:
            micro_value = results[0][op].get(metric, 0)
            layered_value = results[1][op].get(metric, 0)
            
            print(f"{op.capitalize():<20} {metric:<20} {micro_value:<15.2f} {layered_value:<15.2f}")
    
    # Generate plots
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle('Architecture Performance Comparison', fontsize=16)
    
    # Plot 1: Average Latency Comparison
    ax1 = axes[0, 0]
    operations_labels = ['Create', 'Search', 'Match']
    micro_latencies = [results[0][op]["avg_latency_ms"] for op in operations]
    layered_latencies = [results[1][op]["avg_latency_ms"] for op in operations]
    
    x = range(len(operations_labels))
    width = 0.35
    ax1.bar([i - width/2 for i in x], micro_latencies, width, label='Microservices', color='skyblue')
    ax1.bar([i + width/2 for i in x], layered_latencies, width, label='Layered', color='lightcoral')
    ax1.set_xlabel('Operation')
    ax1.set_ylabel('Latency (ms)')
    ax1.set_title('Average Latency by Operation')
    ax1.set_xticks(x)
    ax1.set_xticklabels(operations_labels)
    ax1.legend()
    ax1.grid(axis='y', alpha=0.3)
    
    # Plot 2: Throughput Comparison
    ax2 = axes[0, 1]
    micro_throughput = [results[0][op]["throughput_rps"] for op in operations]
    layered_throughput = [results[1][op]["throughput_rps"] for op in operations]
    
    ax2.bar([i - width/2 for i in x], micro_throughput, width, label='Microservices', color='skyblue')
    ax2.bar([i + width/2 for i in x], layered_throughput, width, label='Layered', color='lightcoral')
    ax2.set_xlabel('Operation')
    ax2.set_ylabel('Throughput (req/s)')
    ax2.set_title('Throughput by Operation')
    ax2.set_xticks(x)
    ax2.set_xticklabels(operations_labels)
    ax2.legend()
    ax2.grid(axis='y', alpha=0.3)
    
    # Plot 3: P95 Latency Comparison
    ax3 = axes[1, 0]
    micro_p95 = [results[0][op]["p95_latency_ms"] for op in operations]
    layered_p95 = [results[1][op]["p95_latency_ms"] for op in operations]
    
    ax3.bar([i - width/2 for i in x], micro_p95, width, label='Microservices', color='skyblue')
    ax3.bar([i + width/2 for i in x], layered_p95, width, label='Layered', color='lightcoral')
    ax3.set_xlabel('Operation')
    ax3.set_ylabel('P95 Latency (ms)')
    ax3.set_title('95th Percentile Latency')
    ax3.set_xticks(x)
    ax3.set_xticklabels(operations_labels)
    ax3.legend()
    ax3.grid(axis='y', alpha=0.3)
    
    # Plot 4: Success Rate
    ax4 = axes[1, 1]
    micro_success = [results[0][op]["success_rate"] for op in operations]
    layered_success = [results[1][op]["success_rate"] for op in operations]
    
    ax4.bar([i - width/2 for i in x], micro_success, width, label='Microservices', color='skyblue')
    ax4.bar([i + width/2 for i in x], layered_success, width, label='Layered', color='lightcoral')
    ax4.set_xlabel('Operation')
    ax4.set_ylabel('Success Rate (%)')
    ax4.set_title('Success Rate by Operation')
    ax4.set_xticks(x)
    ax4.set_xticklabels(operations_labels)
    ax4.set_ylim(0, 105)
    ax4.legend()
    ax4.grid(axis='y', alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('architecture_comparison.png', dpi=300, bbox_inches='tight')
    print("\nComparison chart saved as 'architecture_comparison.png'")

def main():
    """
    Main evaluation function
    """
    print("Lost-and-Found Pets Network - Performance Evaluation")
    print(f"Started at: {datetime.now()}")
    
    # Test configurations
    test_configs = [
        {"name": "Light Load", "requests": 50, "concurrent": 5},
        {"name": "Medium Load", "requests": 200, "concurrent": 20},
        {"name": "Heavy Load", "requests": 500, "concurrent": 50}
    ]
    
    all_results = []
    
    for config in test_configs:
        print(f"\n{'#'*60}")
        print(f"Running {config['name']} Test")
        print(f"{'#'*60}")
        
        # Test Layered Architecture (REST)
        layered_results = run_workload_test(
            LAYERED_BASE_URL,
            "Layered (REST)",
            num_requests=config["requests"],
            concurrent_users=config["concurrent"]
        )
        
        # Wait between tests
        time.sleep(5)
        
        # Note: Microservices would need gRPC client implementation
        # For now, we'll simulate or you'd implement gRPC testing
        
        all_results.append({
            "config": config["name"],
            "layered": layered_results
        })
    
    # Save results to JSON
    with open('evaluation_results.json', 'w') as f:
        json.dump(all_results, f, indent=2)
    
    print(f"\nEvaluation completed at: {datetime.now()}")
    print("Results saved to 'evaluation_results.json'")

if __name__ == "__main__":
    main()
        