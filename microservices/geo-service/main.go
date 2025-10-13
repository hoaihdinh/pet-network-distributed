// microservices/geo-service/main.go
package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"os"
	"strconv"
	"time"

	"github.com/go-redis/redis/v8"
	"google.golang.org/grpc"
	"google.golang.org/grpc/reflection"
	pb "petnetwork/proto"
)

type geoServer struct {
	pb.UnimplementedGeoServiceServer
	rdb         *redis.Client
	reportStub  pb.ReportServiceClient
}

func main() {
	// Redis connection
	redisHost := getEnv("REDIS_HOST", "redis-geo")
	rdb := redis.NewClient(&redis.Options{
		Addr:     fmt.Sprintf("%s:6379", redisHost),
		Password: "",
		DB:       0,
	})

	// Wait for Redis to be ready
	ctx := context.Background()
	for i := 0; i < 30; i++ {
		if err := rdb.Ping(ctx).Err(); err == nil {
			break
		}
		log.Printf("Waiting for Redis... (%d/30)", i+1)
		time.Sleep(2 * time.Second)
	}

	log.Println("Connected to Redis successfully")

	// Connect to Report Service
	reportServiceURL := getEnv("REPORT_SERVICE_URL", "report-service:50051")
	reportConn, err := grpc.Dial(reportServiceURL, grpc.WithInsecure())
	if err != nil {
		log.Fatalf("Failed to connect to Report Service: %v", err)
	}
	defer reportConn.Close()

	reportClient := pb.NewReportServiceClient(reportConn)

	// Start gRPC server
	port := getEnv("GRPC_PORT", "50053")
	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", port))
	if err != nil {
		log.Fatalf("Failed to listen: %v", err)
	}

	grpcServer := grpc.NewServer()
	pb.RegisterGeoServiceServer(grpcServer, &geoServer{
		rdb:        rdb,
		reportStub: reportClient,
	})
	reflection.Register(grpcServer)

	log.Printf("Geo Service listening on port %s", port)
	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("Failed to serve: %v", err)
	}
}

func (s *geoServer) IndexLocation(ctx context.Context, req *pb.IndexLocationRequest) (*pb.IndexLocationResponse, error) {
	if req.Location == nil {
		return &pb.IndexLocationResponse{Success: false}, fmt.Errorf("location is required")
	}

	// Fetch the full report to get type
	report, err := s.reportStub.GetReport(ctx, &pb.GetReportRequest{Id: req.ReportId})
	if err != nil {
		log.Printf("Warning: Could not fetch report %s for indexing: %v", req.ReportId, err)
		// Continue anyway with default type
	}

	reportType := "lost"
	if report != nil && report.Type == pb.ReportType_FOUND {
		reportType = "found"
	}

	geoKey := fmt.Sprintf("geo:%s", reportType)

	// Add to Redis GeoIndex
	// GeoAdd expects longitude, latitude (note the order!)
	err = s.rdb.GeoAdd(ctx, geoKey, &redis.GeoLocation{
		Name:      req.ReportId,
		Longitude: req.Location.Longitude,
		Latitude:  req.Location.Latitude,
	}).Err()

	if err != nil {
		log.Printf("Error indexing location: %v", err)
		return &pb.IndexLocationResponse{Success: false}, err
	}

	log.Printf("Indexed location for report %s at (%.4f, %.4f)",
		req.ReportId, req.Location.Latitude, req.Location.Longitude)

	return &pb.IndexLocationResponse{Success: true}, nil
}

func (s *geoServer) NearbySearch(ctx context.Context, req *pb.NearbySearchRequest) (*pb.NearbySearchResponse, error) {
	if req.Center == nil {
		return nil, fmt.Errorf("center location is required")
	}

	reportType := "lost"
	if req.Type == pb.ReportType_FOUND {
		reportType = "found"
	}

	geoKey := fmt.Sprintf("geo:%s", reportType)

	// GeoRadius: find reports within radius
	results, err := s.rdb.GeoRadius(ctx, geoKey, req.Center.Longitude, req.Center.Latitude, &redis.GeoRadiusQuery{
		Radius:      req.RadiusKm,
		Unit:        "km",
		WithDist:    true,
		WithCoord:   true,
		Sort:        "ASC",
		Count:       50,
	}).Result()

	if err != nil {
		log.Printf("Error performing geo search: %v", err)
		return nil, err
	}

	log.Printf("Found %d reports within %.2f km of (%.4f, %.4f)",
		len(results), req.RadiusKm, req.Center.Latitude, req.Center.Longitude)

	// Fetch full report details for each result
	var reports []*pb.Report
	for _, result := range results {
		reportID := result.Name

		// Fetch full report from Report Service
		report, err := s.reportStub.GetReport(ctx, &pb.GetReportRequest{Id: reportID})
		if err != nil {
			log.Printf("Warning: Could not fetch report %s: %v", reportID, err)
			continue
		}

		reports = append(reports, report)
	}

	return &pb.NearbySearchResponse{
		Reports: reports,
	}, nil
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}