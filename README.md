# Lost-and-Found Pets Network - Distributed System

Original Project: A comprehensive distributed system for matching lost and found pets using two different architectural patterns: **Microservices with gRPC** and **Layered Architecture with REST**.

**Project 3:** The Layered Architecture was used as the base for the implementation of both Raft and 2PC Consensus Algorithms. The layer targeted for both 2PC and Raft is the data-access layer. 2PC was implemented by Jennifer Hernandez. Raft was implemented by Hoai Dinh. 

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

## 📝 Original Functional Requirements 
### FR1: Create Lost/Found Report
### FR2: Nearby Match Search
### FR3: Real-Time Geo Alerts
### FR4: Distributed Match Query
### FR5: Cross-Region Replication & Conflict Resolution

---

## 🏗️ Architecture Comparison

### Architecture 1: Microservices with gRPC (not used for Project 3)

**Communication**: gRPC (efficient, strongly-typed, supports streaming)

**Services (5 Nodes)**:
1. **Report Service** (Port 50051)
2. **Matching Service** (Port 50052)
3. **Geo Service** (Port 50053)
4. **Alert Service** (Port 50054)
5. **Replication Service** (Port 50055)

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

---

## 📁 Project Structure

```
pet-network-distributed/
├── README.md
├── docker-compose-microservices.yml
├── docker-compose-layered.yml
├── docker-compose-layered-2pc.yml
├── docker-compose-layered-raft.yml
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
│   │   ├── base/
│   │   │   ├── Dockerfile
│   │   │   ├── app.py
│   │   │   └── requirements.txt
│   │   ├── 2pc/                # 2PC implementation
│   │   │   ├── Dockerfile
│   │   │   ├── app.py
│   │   │   ├── data_access.proto
│   │   │   ├── data_access_pb2_grpc.py
│   │   │   ├── data_access_pb2.py
│   │   │   └── requirements.txt
│   │   └── raft/               # Raft implementation
│   │       ├── nginx/conf.d
│   │       │   └── data-access.conf
│   │       ├── proto_raft/
│   │       │   ├── raft_pb2_grpc.py
│   │       │   ├── raft_pb2.py
│   │       │   ├── raft_pb2.pyi
│   │       │   └── raft.proto
│   │       ├── Dockerfile
│   │       ├── app.py
│   │       ├── simple_raft.py
│   │       └── requirements.txt
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
There are three ways to start the program based on what services are desired. The options are Microservices Architecture, Layered Arch, or Layered with 2PC Arch. Each have their own compose.yml file and therefore have different start commands. You cannot start more than one at a time.

#### 1. Clone Repository
```bash
git clone https://github.com/hrb-ab/pet-network-distributed.git
cd pet-network-distributed
```

#### 1. Microservices Architecture
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
```bash
# Check Report Service
grpcurl -plaintext localhost:50051 list

# Check health (if HTTP endpoint added)
curl http://localhost:50051/health
```

#### 2. Layered Architecture
```bash
docker-compose -f docker-compose-layered.yml up --build -d

# Check status
docker-compose -f docker-compose-layered.yml ps

# Stop
docker-compose -f docker-compose-layered.yml down -v
```

#### 3. Layered with 2PC Architecture
```bash
docker-compose -f docker-compose-layered-2pc.yml up --build -d

# Check status
docker-compose -f docker-compose-layered-2pc.yml ps

# Check coordinator logs
docker logs -f data-access-1

# Check participant logs (where n could be 2,3,4,5)
docker logs -f data-access-n

# Stop
docker-compose -f docker-compose-layered-2pc.yml down -v
```

#### Layered Verifying & Usage (both 2PC and original)
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
