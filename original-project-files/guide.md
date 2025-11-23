# Complete Implementation Guide - Both Architectures

## 📋 Overview

You now have **all the code** for both architectures. Here's how to set everything up.

---

## Part 1: Layered Architecture (Python + REST) ✅

### Step 1: Create Missing Files

Create these files in your `layered/` directory:

#### 1. Each service needs these 3 files:

**File 1: `Dockerfile`** (same for all services, just change port)
```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .

ENV PYTHONUNBUFFERED=1

EXPOSE 8080

CMD ["python", "app.py"]
```

**File 2: `requirements.txt`** (same for all)
```
Flask==3.0.0
requests==2.31.0
redis==5.0.0
psycopg2-binary==2.9.9
```

**File 3: `app.py`** - Copy from artifacts I created:
- ✅ `api-gateway/app.py` - You have this
- ✅ `business-logic/app.py` - You have this  
- ✅ `data-access/app.py` - You have this
- ❌ `replication-layer/app.py` - Copy from artifact "Replication Service (FR5)"
- ❌ `cache-layer/app.py` - Copy from artifact "Cache Layer (Python + Redis)"

### Step 2: Deploy Layered Architecture

```bash
# From project root
docker-compose -f docker-compose-layered.yml up --build -d

# Check status
docker-compose -f docker-compose-layered.yml ps

# Check logs
docker-compose -f docker-compose-layered.yml logs -f
```

### Step 3: Test Layered Architecture

```bash
# Test health
curl http://localhost:8080/health

# Create a report (FR1)
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
    "description": "Friendly golden retriever",
    "contact_info": "test@example.com"
  }'

# Save the report ID from the response!

# Nearby search (FR2)
curl -X POST http://localhost:8080/api/search/nearby \
  -H "Content-Type: application/json" \
  -d '{
    "location": {"latitude": 40.7128, "longitude": -74.0060},
    "radius_km": 10,
    "type": "lost"
  }'

# Find matches (FR4)
curl "http://localhost:8080/api/matches/REPORT_ID?max_distance=50&limit=10"

# Subscribe to alerts (FR3)
curl -X POST http://localhost:8080/api/alerts/subscribe \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "user123",
    "location": {"latitude": 40.7128, "longitude": -74.0060},
    "radius_km": 10,
    "pet_types": ["dog"]
  }'
```

---

## Part 2: Microservices Architecture (Go + gRPC) 🔧

### Step 1: Create Directory Structure

```bash
cd microservices

# Create all service directories
mkdir -p report-service geo-service matching-service alert-service replication-service
```

### Step 2: Copy Go Code

For each service, create these files:

#### Report Service:
- `microservices/report-service/main.go` - Copy from artifact "Report Service - main.go"
- `microservices/report-service/Dockerfile` - Copy from "Dockerfiles for All Microservices"
- `microservices/report-service/go.mod` - Copy from "go.mod Files for All Microservices"

#### Geo Service:
- `microservices/geo-service/main.go` - Copy from artifact "Geo Service - main.go"
- `microservices/geo-service/Dockerfile` - Copy from Dockerfiles artifact
- `microservices/geo-service/go.mod` - Copy from go.mod artifact

#### Matching Service:
- `microservices/matching-service/main.go` - Copy from artifact "Matching Service - main.go"
- `microservices/matching-service/Dockerfile` - Copy from Dockerfiles artifact
- `microservices/matching-service/go.mod` - Copy from go.mod artifact

### Step 3: Generate gRPC Code

```bash
cd microservices/proto

# Install protoc tools (if not already installed)
# macOS:
brew install protobuf

# Linux:
sudo apt-get install -y protobuf-compiler

# Install Go plugins
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest

# Generate gRPC code from pet_network.proto
protoc --go_out=. --go_opt=paths=source_relative \
       --go-grpc_out=. --go-grpc_opt=paths=source_relative \
       pet_network.proto

# This creates:
# - pet_network.pb.go
# - pet_network_grpc.pb.go
```

### Step 4: Download Go Dependencies

```bash
# For each service
cd microservices/report-service
go mod download
go mod tidy

cd ../geo-service
go mod download
go mod tidy

cd ../matching-service
go mod download
go mod tidy
```

### Step 5: Deploy Microservices

```bash
# From project root
docker-compose -f docker-compose-microservices.yml up --build -d

# Check status
docker-compose -f docker-compose-microservices.yml ps

# Check logs
docker-compose -f docker-compose-microservices.yml logs -f report-service
```

### Step 6: Test Microservices with grpcurl

```bash
# Install grpcurl
# macOS:
brew install grpcurl

# Linux:
go install github.com/fullstorydev/grpcurl/cmd/grpcurl@latest

# List available services
grpcurl -plaintext localhost:50051 list

# List methods for ReportService
grpcurl -plaintext localhost:50051 list petnetwork.ReportService

# Create a report
grpcurl -plaintext -d '{
  "type": "LOST",
  "pet_type": "dog",
  "breed": "labrador",
  "color": "golden",
  "location": {
    "latitude": 40.7128,
    "longitude": -74.0060,
    "address": "New York, NY"
  },
  "description": "Friendly dog",
  "contact_info": "test@example.com"
}' localhost:50051 petnetwork.ReportService/CreateReport

# List reports
grpcurl -plaintext -d '{
  "type": "LOST",
  "limit": 10,
  "offset": 0
}' localhost:50051 petnetwork.ReportService/ListReports
```

---

## Part 3: Performance Evaluation 📊

### Run Benchmarks

```bash
cd evaluation

# Install Python dependencies
pip install requests matplotlib

# Run benchmarks
python benchmark.py
```

### Expected Output:

```
============================================================
Testing Layered (REST) Architecture
Requests: 200, Concurrent Users: 20
============================================================

Phase 1: Creating 200 reports...
Created 200 reports
Create Report Metrics:
  avg_latency_ms: 52.34
  p95_latency_ms: 89.45
  throughput_rps: 19.15

Phase 2: Running 100 nearby searches...
Nearby Search Metrics:
  avg_latency_ms: 28.67
  p95_latency_ms: 51.23
  throughput_rps: 35.12

Phase 3: Running 100 match queries...
Match Query Metrics:
  avg_latency_ms: 73.45
  p95_latency_ms: 142.56
  throughput_rps: 13.66
```

---

## File Checklist ✅

### Layered Architecture Files:

```
layered/
├── api-gateway/
│   ├── app.py ✅
│   ├── Dockerfile ❓
│   └── requirements.txt ❓
├── business-logic/
│   ├── app.py ✅
│   ├── Dockerfile ❓
│   └── requirements.txt ❓
├── data-access/
│   ├── app.py ✅
│   ├── Dockerfile ❓
│   └── requirements.txt ❓
├── replication-layer/
│   ├── app.py ❌ NEED THIS
│   ├── Dockerfile ❌ NEED THIS
│   └── requirements.txt ❌ NEED THIS
└── cache-layer/
    ├── app.py ❌ NEED THIS
    ├── Dockerfile ❌ NEED THIS
    └── requirements.txt ❌ NEED THIS
```

### Microservices Files:

```
microservices/
├── proto/
│   ├── pet_network.proto ✅
│   ├── pet_network.pb.go ❌ GENERATE
│   ├── pet_network_grpc.pb.go ❌ GENERATE
│   └── go.mod ❌ CREATE
├── report-service/
│   ├── main.go ❌ COPY FROM ARTIFACT
│   ├── Dockerfile ❌ COPY FROM ARTIFACT
│   ├── go.mod ❌ COPY FROM ARTIFACT
│   └── go.sum ⚙️ AUTO-GENERATED
├── geo-service/
│   ├── main.go ❌ COPY FROM ARTIFACT
│   ├── Dockerfile ❌ COPY FROM ARTIFACT
│   ├── go.mod ❌ COPY FROM ARTIFACT
│   └── go.sum ⚙️ AUTO-GENERATED
└── matching-service/
    ├── main.go ❌ COPY FROM ARTIFACT
    ├── Dockerfile ❌ COPY FROM ARTIFACT
    ├── go.mod ❌ COPY FROM ARTIFACT
    └── go.sum ⚙️ AUTO-GENERATED
```

---

## Quick Start Commands 🚀

### Option A: Layered Only (Fastest - Start Here!)

```bash
# 1. Complete missing files (replication-layer, cache-layer)
# 2. Deploy
docker-compose -f docker-compose-layered.yml up --build -d

# 3. Test
curl http://localhost:8080/health
```

### Option B: Both Architectures (Complete)

```bash
# 1. Deploy Layered
docker-compose -f docker-compose-layered.yml up --build -d

# 2. Generate gRPC code
cd microservices/proto
protoc --go_out=. --go-grpc_out=. pet_network.proto

# 3. Deploy Microservices
cd ../..
docker-compose -f docker-compose-microservices.yml up --build -d

# 4. Test both
curl http://localhost:8080/health  # Layered
grpcurl -plaintext localhost:50051 list  # Microservices
```

---

## Troubleshooting 🔧

### Layered Architecture Issues:

**Services won't start:**
```bash
# Check logs
docker-compose -f docker-compose-layered.yml logs api-gateway

# Rebuild
docker-compose -f docker-compose-layered.yml up --build --force-recreate
```

**Database connection errors:**
```bash
# Check PostgreSQL
docker-compose -f docker-compose-layered.yml logs postgres-layered

# Restart database
docker-compose -f docker-compose-layered.yml restart postgres-layered
```

### Microservices Issues:

**gRPC generation fails:**
```bash
# Make sure protoc is installed
protoc --version

# Reinstall Go plugins
go install google.golang.org/protobuf/cmd/protoc-gen-go@latest
go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest
```

**Go build errors:**
```bash
# Clean and rebuild
go clean -modcache
go mod download
go mod tidy
```

---

## Success Criteria ✅

You'll know it's working when:

### Layered:
- ✅ All 5 health endpoints return 200
- ✅ Can create reports via API
- ✅ Can search nearby reports
- ✅ Can find matches
- ✅ Can subscribe to alerts

### Microservices:
- ✅ All 5 gRPC services are running
- ✅ grpcurl can list services
- ✅ Can create reports via gRPC
- ✅ Services can communicate with each other

### Evaluation:
- ✅ Benchmark script runs successfully
- ✅ Have performance comparison data
- ✅ Can generate comparison graphs

---

## Next Steps After Setup 📈

1. **Test all 5 functional requirements** on both architectures
2. **Run performance benchmarks** (light, medium, heavy load)
3. **Document findings** in your report
4. **Create comparison charts**
5. **Write evaluation** of trade-offs

---

## Timeline Estimate ⏱️

- **Layered Setup**: 2-4 hours
- **Microservices Setup**: 4-8 hours  
- **Testing**: 2-3 hours
- **Evaluation**: 2-4 hours
- **Total**: 10-19 hours (1-2 days of focused work)

Good luck! 🚀