// microservices/replication-service/main.go
package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"os"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/reflection"
	pb "petnetwork/proto"
)

type replicationServer struct {
	pb.UnimplementedReplicationServiceServer
	reportStub pb.ReportServiceClient
	region     string
	peerURLs   []string
}

func main() {
	// Connect to Report Service
	reportServiceURL := getEnv("REPORT_SERVICE_URL", "report-service:50051")
	reportConn, err := grpc.Dial(reportServiceURL, grpc.WithInsecure())
	if err != nil {
		log.Fatalf("Failed to connect to Report Service: %v", err)
	}
	defer reportConn.Close()

	reportClient := pb.NewReportServiceClient(reportConn)

	// Get configuration
	region := getEnv("REGION", "us-east")
	peerRegionsStr := getEnv("PEER_REGIONS", "")
	var peerURLs []string
	if peerRegionsStr != "" {
		peerURLs = strings.Split(peerRegionsStr, ",")
	}

	// Start gRPC server
	port := getEnv("GRPC_PORT", "50055")
	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", port))
	if err != nil {
		log.Fatalf("Failed to listen: %v", err)
	}

	grpcServer := grpc.NewServer()
	pb.RegisterReplicationServiceServer(grpcServer, &replicationServer{
		reportStub: reportClient,
		region:     region,
		peerURLs:   peerURLs,
	})
	reflection.Register(grpcServer)

	log.Printf("Replication Service listening on port %s (region: %s)", port, region)
	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("Failed to serve: %v", err)
	}
}

func (s *replicationServer) SyncData(stream pb.ReplicationService_SyncDataServer) error {
	log.Println("Sync stream established")
	
	for {
		req, err := stream.Recv()
		if err != nil {
			return err
		}

		log.Printf("Received sync from region: %s (%d reports)", req.SourceRegion, len(req.Reports))

		// Sync each report
		var syncedIDs []string
		for _, report := range req.Reports {
			// Try to get existing report
			existing, err := s.reportStub.GetReport(context.Background(), &pb.GetReportRequest{
				Id: report.Id,
			})

			if err != nil {
				// Report doesn't exist, create it
				_, createErr := s.reportStub.CreateReport(context.Background(), &pb.CreateReportRequest{
					Type:        report.Type,
					PetType:     report.PetType,
					Breed:       report.Breed,
					Color:       report.Color,
					Location:    report.Location,
					Description: report.Description,
					PhotoUrls:   report.PhotoUrls,
					ContactInfo: report.ContactInfo,
				})

				if createErr == nil {
					syncedIDs = append(syncedIDs, report.Id)
					log.Printf("Created new report: %s", report.Id)
				}
			} else {
				// Report exists, check for conflicts
				if report.Timestamp > existing.Timestamp {
					log.Printf("Conflict detected for %s: remote is newer", report.Id)
					// In production, would update the report
					syncedIDs = append(syncedIDs, report.Id)
				}
			}
		}

		// Send response
		if err := stream.Send(&pb.SyncDataResponse{
			Success:   true,
			SyncedIds: syncedIDs,
		}); err != nil {
			return err
		}
	}
}

func (s *replicationServer) ResolveConflict(ctx context.Context, req *pb.ConflictResolutionRequest) (*pb.ConflictResolutionResponse, error) {
	conflict := req.Conflict
	
	log.Printf("Resolving conflict for report: %s", conflict.ReportId)

	var resolved *pb.Report

	// Apply resolution strategy
	switch req.Strategy {
	case pb.ResolutionStrategy_LAST_WRITE_WINS:
		if conflict.RemoteVersion.Timestamp > conflict.LocalVersion.Timestamp {
			resolved = conflict.RemoteVersion
		} else {
			resolved = conflict.LocalVersion
		}
	case pb.ResolutionStrategy_HIGHEST_VERSION:
		if conflict.RemoteVersion.Version > conflict.LocalVersion.Version {
			resolved = conflict.RemoteVersion
		} else {
			resolved = conflict.LocalVersion
		}
	default:
		resolved = conflict.LocalVersion
	}

	log.Printf("Conflict resolved using %s strategy", req.Strategy)

	return &pb.ConflictResolutionResponse{
		ResolvedReport: resolved,
		Success:        true,
	}, nil
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}