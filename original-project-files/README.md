# Lost-and-Found Pets Network - Distributed System

A comprehensive distributed system for matching lost and found pets using two different architectural patterns: **Microservices with gRPC** and **Layered Architecture with REST**.

## 📋 Table of Contents

- [System Overview](#system-overview)
- [Functional Requirements](#functional-requirements)
- [Architecture Comparison](#architecture-comparison)
- [Project Structure](#project-structure)
- [Setup Instructions](#setup-instructions)
- [Performance Evaluation](#performance-evaluation)
- [Trade-offs Analysis](#trade-offs-analysis)

---

## 🎯 System Overview

This distributed system implements a pet lost-and-found matching service that:
- Operates across 5+ nodes
- Supports geospatial queries for nearby matches
- Provides real-time alerting
- Handles cross-region replication with conflict resolution
- Compares two architectural approaches

---

## 📝 Functional Requirements

### FR1: Create Lost/Found Report
- Submit detailed pet reports (type, breed, color, location, photos, contact)
- Assign unique IDs with geospatial indexing
- Support both "lost" and "found" report types

### FR2: Nearby Match Search
- Query reports within specified radius (5km-50km)
- Filter by pet characteristics
- Return ranked results by similarity and proximity

### FR3: Real-Time Geo Alerts
- Subscribe to alerts for specific geographic regions
- Receive push notifications for matching reports
- Support multiple concurrent subscriptions

### FR4: Distributed Match Query
- Execute complex queries across multiple nodes
- Aggregate results from different regions
- Calculate match probability using similarity scoring

### FR5: Cross-Region Replication & Conflict Resolution
- Replicate data across geographic regions
- Handle concurrent updates with multiple strategies:
  - **Last-Write-Wins (LWW)**: Choose most recent timestamp
  - **Highest-Version**: Select highest version number
  - **Manual Merge**: Combine non-conflicting fields
- Maintain eventual consistency using vector clocks

---

## 🏗️ Architecture Comparison

### Architecture 1: Microservices with gRPC

**Communication**: gRPC (efficient, strongly-typed, supports streaming)

**Services (5 Nodes)**:
1. **Report Service** (Port 50051)
   - Handles CRUD operations for reports
   - PostgreSQL with PostGIS for geospatial data
   
2. **Matching Service** (Port 50052)
   - Similarity matching algorithms
   - Match score calculation
   
3. **Geo Service** (Port 50053)
   - Geospatial indexing and queries
   - Redis for fast geo-queries
   
4. **Alert Service** (Port 50054)
   - Real-time notification subscriptions
   - gRPC streaming for push alerts
   
5. **Replication Service** (Port 50055)
   - Cross-region data synchronization
   - Conflict detection and resolution

**Advantages**:
- Independent scaling of services
- Technology heterogeneity (Go, Python, etc.)
- Strong typing with Protocol Buffers
- Efficient binary serialization
- Built-in streaming support

**Disadvantages**:
- Higher operational complexity
- More network hops
- Service discovery challenges
- Debugging across services

---

### Architecture 2: Layered with REST

**Communication**: HTTP REST (standard, widely supported, human-readable)

**Layers (5 Nodes)**:
1. **API Gateway** (Port 8080)
   - REST endpoint exposure
   - Request validation and routing
   
2. **Business Logic Layer** (Port 8081)
   - Core matching algorithms
   - Business rule enforcement
   
3. **Data Access Layer** (Port 8082)
   - Database abstraction
   - Query optimization
   
4. **Replication Layer** (Port 8083)
   - Cross-region synchronization
   - Conflict resolution strategies
   
5. **Cache Layer** (Port 8084)
   - Redis for hot data
   - Geospatial indexing

**Advantages**:
- Simpler to understand and debug
- Clear separation of concerns
- Easier testing (layer by layer)
- Standard HTTP tools work everywhere
- Lower learning curve

**Disadvantages**:
- Tight coupling between layers
- All layers must use compatible technologies
- Harder to scale individual components
- Less efficient serialization (JSON)

---

## 📁 Project Structure

```
pet-network-distributed/
├── README.md
├── docker-compose-microservices.yml
├── docker-compose-layered.yml
│
├── microservices/              # Microservices Architecture
│   ├── proto/
│   │   └── pet_network.proto
│   ├── report-service/
│   │   ├── Dockerfile
│   │   ├── main.go
│   │   ├── go.mod
│   │   └── go.sum
│   ├── matching-service/
│   │   ├── Dockerfile
│   │   └── main.go
│   ├── geo-service/
│   │   ├── Dockerfile
│   │   └── main.go
│   ├── alert-service/
│   │   ├── Dockerfile
│   │   └── main.go
│   └── replication-service/
│       ├── Dockerfile
│       └── main.go
│
├── layered/                    # Layered Architecture
│   ├── api-gateway/
│   │   ├── Dockerfile
│   │   ├── app.py
│   │   └── requirements.txt
│   ├── business-logic/
│   │   ├── Dockerfile
│   │   ├── app.py
│   │   └── requirements.txt
│   ├── data-access/
│   │   ├── Dockerfile
│   │   ├── app.py
│   │   └── requirements.txt
│   ├── replication-layer/
│   │   ├── Dockerfile
│   │   ├── app.py
│   │   └── requirements.txt
│   └── cache-layer/
│       ├── Dockerfile
│       ├── app.py
│       └── requirements.txt
│
└── evaluation/                 # Performance Testing
    ├── benchmark.py
    ├── grpc_client.py
    └── requirements.txt
```

---

## 🚀 Setup Instructions

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+
- Python 3.11+ (for evaluation)
- Go 1.21+ (for microservices)

### Quick Start

#### 1. Clone Repository
```bash
git clone https://github.com/hrb-ab/pet-network-distributed.git
cd pet-network-distributed
```

#### 2. Start Microservices Architecture
```bash
# Generate gRPC code from proto files
cd microservices/proto
protoc --go_out=. --go-grpc_out=. pet_network.proto

# Start all services
cd ../..
docker-compose -f docker-compose-microservices.yml up --build -d

# Check status
docker-compose -f docker-compose-microservices.yml ps
```

#### 3. Start Layered Architecture
```bash
docker-compose -f docker-compose-layered.yml up --build -d

# Check status
docker-compose -f docker-compose-layered.yml ps
```

#### 4. Verify Services

**Microservices:**
```bash
# Check Report Service
grpcurl -plaintext localhost:50051 list

# Check health (if HTTP endpoint added)
curl http://localhost:50051/health
```

**Layered:**
```bash
# Check API Gateway
curl http://localhost:8080/health

# Create a test report
curl -X POST http://localhost:8080/api/reports \
  -H "Content-Type: application/json" \
  -d '{
    "type": "lost",
    "pet_type": "dog",
    "breed": "labrador",
    "color": "golden",
    "location": {
      "latitude": 40.7128,
      "longitude": -74.0060,
      "address": "New York, NY"
    },
    "description": "Lost golden labrador, very friendly",
    "contact_info": "john@example.com"
  }'
```

---

## 📊 Performance Evaluation

### Running Benchmarks

```bash
cd evaluation

# Install dependencies
pip install -r requirements.txt

# Run evaluation
python benchmark.py
```

### Evaluation Scenarios

#### 1. Light Load
- 50 requests
- 5 concurrent users
- Measures baseline performance

#### 2. Medium Load
- 200 requests
- 20 concurrent users
- Realistic production traffic

#### 3. Heavy Load
- 500 requests
- 50 concurrent users
- Stress testing and scalability

### Metrics Collected

- **Latency**: Average, P50, P95, P99, Min, Max
- **Throughput**: Requests per second
- **Success Rate**: % of successful requests
- **Operation Breakdown**: Create, Search, Match queries

### Sample Results

```
Operation            Metric               Microservices   Layered        
----------------------------------------------------------------------
Create              avg_latency_ms       45.23          52.18          
Create              p95_latency_ms       78.45          89.32          
Create              throughput_rps       22.10          19.15          
Search              avg_latency_ms       23.12          28.45          
Search              p95_latency_ms       42.67          51.23          
Search              throughput_rps       43.25          35.12          
Match               avg_latency_ms       67.89          73.21          
Match               p95_latency_ms       125.34         142.56         
Match               throughput_rps       14.73          13.66          
```

---

## ⚖️ Trade-offs Analysis

### Performance

**Winner: Microservices (marginal)**
- gRPC binary protocol is ~20-30% faster than JSON
- But adds network latency from service hops
- Layered architecture has fewer network calls

**Key Finding**: For < 1000 RPS, difference is negligible

### Scalability

**Winner: Microservices (clear)**
- Independent service scaling
- Can scale geo-service separately for heavy query load
- Layered must scale entire stack together

**Recommendation**: Use microservices for >10K RPS

### Development Complexity

**Winner: Layered (significant)**
- Easier to understand and debug
- Simpler deployment (fewer moving parts)
- Standard HTTP tools work everywhere

**Consideration**: Team expertise matters more than architecture

### Operational Complexity

**Winner: Layered**
- Fewer containers to manage
- Simpler monitoring and logging
- Easier troubleshooting

**Microservices Overhead**:
- Service discovery
- Distributed tracing
- More sophisticated monitoring

### Fault Tolerance

**Winner: Microservices**
- Isolated failures (one service down ≠ system down)
- Circuit breakers between services
- Layered: Layer failure affects all above it

### Technology Flexibility

**Winner: Microservices**
- Can use Go, Python, Java per service
- Layered: Usually one language/framework

### Data Consistency

**Winner: Layered (simpler)**
- Direct database access in data layer
- Microservices need distributed transaction patterns
- Both support eventual consistency for replication

---

## 🔧 Configuration

### Environment Variables

**Microservices:**
```env
# Report Service
DB_HOST=postgres-reports
GRPC_PORT=50051
REGION=us-east

# Replication Service
PEER_REGIONS=us-west:50055,eu-central:50055
```

**Layered:**
```env
# API Gateway
BUSINESS_LOGIC_URL=http://business-logic:8081
PORT=8080

# Replication Layer
PEER_URLS=http://peer-region-1:8083,http://peer-region-2:8083
REGION=us-east
```

---

## 🧪 Testing

### Unit Tests
```bash
# Microservices
cd microservices/report-service
go test ./...

# Layered
cd layered/api-gateway
python -m pytest tests/
```

### Integration Tests
```bash
# Start services first
docker-compose -f docker-compose-layered.yml up -d

# Run integration tests
cd evaluation
python -m pytest integration_tests/
```

---

## 📈 Monitoring

### Metrics Endpoints

**Layered:**
- API Gateway: `http://localhost:8080/metrics`
- Business Logic: `http://localhost:8081/metrics`

### Logging

```bash
# View logs
docker-compose -f docker-compose-layered.yml logs -f

# Specific service
docker-compose -f docker-compose-layered.yml logs -f api-gateway
```
