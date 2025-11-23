# Lost-and-Found Pets Network with Fault Tolerance (2PC/Raft) - Distributed System

**Original Project:** A comprehensive distributed system for matching lost and found pets using two different architectural patterns: **Microservices with gRPC** and **Layered Architecture with REST**.  
View the original project README.md [here](/original-project-files/README.md)

**Fault Tolerance Implementation:** The Layered Architecture was used as the base for the implementation of both Raft and 2PC Consensus Algorithms. The specific layer targeted for both 2PC and Raft is the data-access layer. 2PC was implemented by Jennifer Hernandez. Raft was implemented by Hoai Dinh.  
Repository Link: https://github.com/hoaihdinh/pet-network-distributed

---

## 2PC & Raft Implementation Overview

Both implementations focused on the data-access layer of the Layered Architecture in the original project. This layer handles client requests to retrieve, create, or update user reports in the Postgres layer. Both 2PC and Raft work with a set of 5 replicated data-access nodes to replace the layer. The Raft implementation also includes an NGINX proxy to the data-access layer, which forwards client requests to any of the replicated nodes.

Since the data-access layer interacts with a Postgres database on a separate node/container, only the coordinator (2PC) or leader node (Raft) execute operations. If all nodes execute the operation, then the single client request would be applied to the Postgres database multiple times, which could result in an erroneous database state.

Note that the original distributed system only exposes the retrieval and creation of user reports from the data-access layer to clients (based on the available endpoints in the API Gateway layer). As such, both implementations are focused on adding Fault Tolerance via 2PC or Raft to the functionality of the creation of user reports (Functional Requirement 1: Create Lost/Found Report).

---

## Project Structure

```
pet-network-distributed/
├── README.md                         # This file
├── RaftTesting.pdf
├── docker-compose-microservices.yml
├── docker-compose-layered.yml
├── docker-compose-layered-2pc.yml    # NEW (Runs with 2PC data-access)
├── docker-compose-layered-raft.yml   # NEW (Runs with Raft data-access)
│
├── original-project-files/   # Contains files from the original repository that are not relavent to this project
│                             # Also contains the original project's README.md file
│
├── microservices/            # Microservices Architecture
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
├── layered/                  # Layered Architecture (Modified!)
│   ├── api-gateway/
│   │   ├── Dockerfile
│   │   ├── app.py
│   │   └── requirements.txt
│   ├── business-logic/
│   │   ├── Dockerfile
│   │   ├── app.py
│   │   └── requirements.txt
│   ├── data-access/          # Added 2PC and Raft verions
│   │   ├── base/
│   │   │   ├── Dockerfile
│   │   │   ├── app.py
│   │   │   └── requirements.txt
│   │   ├── 2pc/              # 2PC implementation
│   │   │   ├── Dockerfile
│   │   │   ├── app.py
│   │   │   ├── data_access.proto
│   │   │   ├── data_access_pb2_grpc.py
│   │   │   ├── data_access_pb2.py
│   │   │   └── requirements.txt
│   │   └── raft/             # Raft implementation
│   │       ├── nginx/conf.d/
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
└── evaluation/
    ├── benchmark.py
    ├── grpc_client.py
    └── requirements.txt
```

---

## How to Compile and Run

### Prerequisites

- Docker 20.10+
- Docker Compose 2.0+

### Quick Start
Since the consensus algorithms were both implemented on the Layered Architecture there are three versions of the Layered Architecture according to the type of consensus desired: None/Base, 2PC, or Raft. Each have their own compose.yml file and therefore have different start commands. You cannot start more than one at a time.  
View bottom of README file, under Unusual Situations, Initialization Issues, for supplemental initialization information.

#### 1. Enter the Project Directory (Clone the Repository if needed)
```bash
git clone https://github.com/hoaihdinh/pet-network-distributed # Optional
cd pet-network-distributed
```

#### 2. Chose a Version of the Data Access Layer to Use
- **Version 1: Layered Architecture (Base)**
```bash
# Compile and run the project
docker-compose -f docker-compose-layered.yml up --build -d

# Check status
docker-compose -f docker-compose-layered.yml ps

# Stop
docker-compose -f docker-compose-layered.yml down -v
```

- **Version 2: Layered Architecture with 2PC**
```bash
# Compile and run the project
docker-compose -f docker-compose-layered-2pc.yml up --build -d

# Check status
docker-compose -f docker-compose-layered-2pc.yml ps

# Check coordinator logs
docker logs -f data-access-1

# Check participant logs (where n could be one of the following: 2,3,4,5)
docker logs -f data-access-<n>

# Stop
docker-compose -f docker-compose-layered-2pc.yml down -v
```

- **Version 3: Layered Architecture with Raft**
```bash
# Compile and run the project
docker-compose -f docker-compose-layered-raft.yml up --build -d

# Check status
docker-compose -f docker-compose-layered-raft.yml ps

# Check raft node logs (where node_id could be one of the following: 1,2,3,4,5)
docker logs -f data-access-raft-node-<node_id>

# Stop
docker-compose -f docker-compose-layered-raft.yml down -v
```

#### 3. Layered Verifying & Usage (All Versions)
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

## Raft Implementation Testing

5 total test cases were used to evaluate the Raft implementation:
1. Current Leader Node Crashes, A New Leader Gets Elected
2. Nodes Do Not Promote From Candidate State to Leader State Without Majority Votes
3. Logs and Commit Indices Are Replicated In the Cluster
4. Follower Nodes Properly Forwards ClientRequest to the Leader Node And Client Receives Response
5. The Raft Cluster Informs The Client If There Is No Leader Node. However, the Raft Cluster Can Still Serve Read Only Requests.

All test cases were evaluated by running the project with the raft version of the data-access layer.  
Note that line 14 of [simple_raft.py](layered/data-access/raft/simple_raft.py) is changed from `logger.setLevel(logging.INFO)` to `logger.setLevel(logging.DEBUG)`.

A more detailed test report can be found [here](/RaftTesting.pdf)

---

## Unusual Situations

### Initialization Issues
Due to details in the ORIGINAL project implementation, the layered architecture may fail to initialize the database. This was always the case for Jennifer, and never the case for Hoai, despite using the same initialization commands that were detailed by the creator. Finding the cause of this seemed outside the scope of this project, so here are steps that allow the initialization to complete correctly every time.

```bash
# Stopping all services
docker-compose -f docker-compose-layered-2pc.yml down -v

# Start database first
docker-compose -f docker-compose-layered-2pc.yml up -d postgres-layered redis-layered

# Wait for about 10 seconds, then validate readiness using
docker exec postgres-layered pg_isready -U petuser

# Start application services
docker-compose -f docker-compose-layered-2pc.yml build --no-cache
docker-compose -f docker-compose-layered-2pc.yml up -d
```

Note that this could still happen for any of the project implementation versions (Base/2PC/Raft). If that is the case, then just replace the yml files in the list of commands above with the desired one.

### Raft Leader Node In Context of the Application
It is important to note that communication from the business-logic layer to the data-access layer to serve client requests has a timeout. This means that if the data-access layer takes too long to process a request, the business-logic layer will flag the server as unavailable and send that message to the client.  
Due to the scope of the project, this interaction and behavior was never addressed as this would involve either changing the logic of the original data-access layer and/or changing the logic of the business-logic layer. The raft implementation was focused on only adding a raft system to the data-access layer to require consensus when creating reports objects in the Postgres database. There is no system in place to cancel operations (either by timeout or manually) added to the raft log as this is only a simplified Raft implementation. Also, the data-access layer has no endpoint to delete reports, in an attempt to undo the report creation if it could detect that the business-logic layer closed the connection.

As such, there may be undefined or unintended behavior when the client submits a create report request and there is a leader raft node, but the leader node is unable to obtain a majority ACKs to execute the client request before the business-logic layer timesout. If the leader node never gets majority ACKs on this client operation, then the client request will never be executed. If the leader node eventually does get majority ACKs, then the client request will be executed despite being unable to send the result to the client as the request was flagged as timed out by the business-logic layer.

However, if a client request was made directly to the Raft Cluster to create a report, and that cluster has a leader but not enough nodes for consensus, then the client request will hang until the leader can obtain a majority ACKs to commit and execute the request.
