// microservices/matching-service/main.go
package main

import (
	"context"
	"fmt"
	"log"
	"math"
	"net"
	"os"
	"sort"
	"strings"

	"google.golang.org/grpc"
	"google.golang.org/grpc/reflection"
	pb "petnetwork/proto"
)

type matchingServer struct {
	pb.UnimplementedMatchingServiceServer
	reportStub pb.ReportServiceClient
	geoStub    pb.GeoServiceClient
}

func main() {
	// Connect to Report Service
	reportServiceURL := getEnv("REPORT_SERVICE_URL", "report-service:50051")
	reportConn, err := grpc.Dial(reportServiceURL, grpc.WithInsecure())
	if err != nil {
		log.Fatalf("Failed to connect to Report Service: %v", err)
	}
	defer reportConn.Close()

	// Connect to Geo Service
	geoServiceURL := getEnv("GEO_SERVICE_URL", "geo-service:50053")
	geoConn, err := grpc.Dial(geoServiceURL, grpc.WithInsecure())
	if err != nil {
		log.Fatalf("Failed to connect to Geo Service: %v", err)
	}
	defer geoConn.Close()

	reportClient := pb.NewReportServiceClient(reportConn)
	geoClient := pb.NewGeoServiceClient(geoConn)

	// Start gRPC server
	port := getEnv("GRPC_PORT", "50052")
	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", port))
	if err != nil {
		log.Fatalf("Failed to listen: %v", err)
	}

	grpcServer := grpc.NewServer()
	pb.RegisterMatchingServiceServer(grpcServer, &matchingServer{
		reportStub: reportClient,
		geoStub:    geoClient,
	})
	reflection.Register(grpcServer)

	log.Printf("Matching Service listening on port %s", port)
	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("Failed to serve: %v", err)
	}
}

func (s *matchingServer) FindMatches(ctx context.Context, req *pb.FindMatchesRequest) (*pb.FindMatchesResponse, error) {
	// Get the source report
	sourceReport, err := s.reportStub.GetReport(ctx, &pb.GetReportRequest{Id: req.ReportId})
	if err != nil {
		return nil, fmt.Errorf("failed to get source report: %v", err)
	}

	// Determine opposite type (lost -> found, found -> lost)
	oppositeType := pb.ReportType_FOUND
	if sourceReport.Type == pb.ReportType_FOUND {
		oppositeType = pb.ReportType_LOST
	}

	// Search for nearby reports of opposite type
	nearbyResp, err := s.geoStub.NearbySearch(ctx, &pb.NearbySearchRequest{
		Center:   sourceReport.Location,
		RadiusKm: req.MaxDistanceKm,
		Type:     oppositeType,
	})

	if err != nil {
		log.Printf("Error searching nearby: %v", err)
		return &pb.FindMatchesResponse{Matches: []*pb.MatchResult{}}, nil
	}

	// Calculate match scores for each nearby report
	var matches []*pb.MatchResult
	for _, candidateReport := range nearbyResp.Reports {
		// Calculate match score
		scoreResp, err := s.CalculateMatchScore(ctx, &pb.MatchScoreRequest{
			Report1: sourceReport,
			Report2: candidateReport,
		})

		if err != nil {
			log.Printf("Error calculating score: %v", err)
			continue
		}

		// Calculate distance
		distance := haversineDistance(
			sourceReport.Location.Latitude,
			sourceReport.Location.Longitude,
			candidateReport.Location.Latitude,
			candidateReport.Location.Longitude,
		)

		matches = append(matches, &pb.MatchResult{
			Report:     candidateReport,
			MatchScore: scoreResp.Score,
			DistanceKm: distance,
		})
	}

	// Sort by match score (highest first)
	sort.Slice(matches, func(i, j int) bool {
		return matches[i].MatchScore > matches[j].MatchScore
	})

	// Limit results
	if req.Limit > 0 && int(req.Limit) < len(matches) {
		matches = matches[:req.Limit]
	}

	log.Printf("Found %d matches for report %s", len(matches), req.ReportId)

	return &pb.FindMatchesResponse{Matches: matches}, nil
}

func (s *matchingServer) CalculateMatchScore(ctx context.Context, req *pb.MatchScoreRequest) (*pb.MatchScoreResponse, error) {
	report1 := req.Report1
	report2 := req.Report2

	score := 0.0
	maxScore := 100.0
	var matchingFeatures []string

	// Pet type match (40 points)
	if strings.EqualFold(report1.PetType, report2.PetType) {
		score += 40
		matchingFeatures = append(matchingFeatures, "pet_type")
	}

	// Breed match (20 points)
	breed1 := strings.ToLower(report1.Breed)
	breed2 := strings.ToLower(report2.Breed)
	if breed1 != "" && breed2 != "" {
		if breed1 == breed2 {
			score += 20
			matchingFeatures = append(matchingFeatures, "breed_exact")
		} else if strings.Contains(breed1, breed2) || strings.Contains(breed2, breed1) {
			score += 10
			matchingFeatures = append(matchingFeatures, "breed_partial")
		}
	}

	// Color match (20 points)
	color1 := strings.ToLower(report1.Color)
	color2 := strings.ToLower(report2.Color)
	if color1 != "" && color2 != "" {
		if color1 == color2 {
			score += 20
			matchingFeatures = append(matchingFeatures, "color_exact")
		} else if strings.Contains(color1, color2) || strings.Contains(color2, color1) {
			score += 10
			matchingFeatures = append(matchingFeatures, "color_partial")
		}
	}

	// Time proximity (20 points)
	timeDiffDays := float64(abs(report1.Timestamp-report2.Timestamp)) / 86400.0
	if timeDiffDays <= 1 {
		score += 20
		matchingFeatures = append(matchingFeatures, "time_1day")
	} else if timeDiffDays <= 3 {
		score += 15
		matchingFeatures = append(matchingFeatures, "time_3days")
	} else if timeDiffDays <= 7 {
		score += 10
		matchingFeatures = append(matchingFeatures, "time_1week")
	} else if timeDiffDays <= 14 {
		score += 5
		matchingFeatures = append(matchingFeatures, "time_2weeks")
	}

	// Normalize to percentage
	normalizedScore := (score / maxScore) * 100

	return &pb.MatchScoreResponse{
		Score:            normalizedScore,
		MatchingFeatures: matchingFeatures,
	}, nil
}

// Haversine formula to calculate distance between two coordinates
func haversineDistance(lat1, lon1, lat2, lon2 float64) float64 {
	const earthRadius = 6371.0 // Earth's radius in kilometers

	// Convert to radians
	lat1Rad := lat1 * math.Pi / 180
	lat2Rad := lat2 * math.Pi / 180
	deltaLat := (lat2 - lat1) * math.Pi / 180
	deltaLon := (lon2 - lon1) * math.Pi / 180

	a := math.Sin(deltaLat/2)*math.Sin(deltaLat/2) +
		math.Cos(lat1Rad)*math.Cos(lat2Rad)*
			math.Sin(deltaLon/2)*math.Sin(deltaLon/2)

	c := 2 * math.Atan2(math.Sqrt(a), math.Sqrt(1-a))

	return earthRadius * c
}

func abs(x int64) int64 {
	if x < 0 {
		return -x
	}
	return x
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}