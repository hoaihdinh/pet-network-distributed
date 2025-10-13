// microservices/alert-service/main.go
package main

import (
	"context"
	"fmt"
	"log"
	"net"
	"os"
	"time"

	"github.com/go-redis/redis/v8"
	"google.golang.org/grpc"
	"google.golang.org/grpc/reflection"
	pb "petnetwork/proto"
)

type alertServer struct {
	pb.UnimplementedAlertServiceServer
	rdb        *redis.Client
	geoStub    pb.GeoServiceClient
}

func main() {
	// Redis connection
	redisHost := getEnv("REDIS_HOST", "redis-geo")
	rdb := redis.NewClient(&redis.Options{
		Addr:     fmt.Sprintf("%s:6379", redisHost),
		Password: "",
		DB:       0,
	})

	// Wait for Redis
	ctx := context.Background()
	for i := 0; i < 30; i++ {
		if err := rdb.Ping(ctx).Err(); err == nil {
			break
		}
		log.Printf("Waiting for Redis... (%d/30)", i+1)
		time.Sleep(2 * time.Second)
	}

	log.Println("Connected to Redis successfully")

	// Connect to Geo Service
	geoServiceURL := getEnv("GEO_SERVICE_URL", "geo-service:50053")
	geoConn, err := grpc.Dial(geoServiceURL, grpc.WithInsecure())
	if err != nil {
		log.Fatalf("Failed to connect to Geo Service: %v", err)
	}
	defer geoConn.Close()

	geoClient := pb.NewGeoServiceClient(geoConn)

	// Start gRPC server
	port := getEnv("GRPC_PORT", "50054")
	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", port))
	if err != nil {
		log.Fatalf("Failed to listen: %v", err)
	}

	grpcServer := grpc.NewServer()
	pb.RegisterAlertServiceServer(grpcServer, &alertServer{
		rdb:     rdb,
		geoStub: geoClient,
	})
	reflection.Register(grpcServer)

	log.Printf("Alert Service listening on port %s", port)
	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("Failed to serve: %v", err)
	}
}

func (s *alertServer) Subscribe(req *pb.SubscribeRequest, stream pb.AlertService_SubscribeServer) error {
	log.Printf("New subscription from user: %s", req.UserId)
	
	// Store subscription in Redis
	subscriptionKey := fmt.Sprintf("subscription:%s:%d", req.UserId, time.Now().Unix())
	
	ctx := context.Background()
	subscriptionData := map[string]interface{}{
		"user_id":   req.UserId,
		"latitude":  req.Center.Latitude,
		"longitude": req.Center.Longitude,
		"radius_km": req.RadiusKm,
	}
	
	// Store subscription (simplified for demo)
	for key, value := range subscriptionData {
		s.rdb.HSet(ctx, subscriptionKey, key, value)
	}
	s.rdb.Expire(ctx, subscriptionKey, 24*time.Hour)
	
	log.Printf("Subscription created: %s", subscriptionKey)
	
	// Keep stream open (in production, use Redis Pub/Sub)
	// For demo, just keep connection alive
	select {
	case <-stream.Context().Done():
		log.Printf("Client disconnected: %s", req.UserId)
		return stream.Context().Err()
	}
}

func (s *alertServer) Unsubscribe(ctx context.Context, req *pb.UnsubscribeRequest) (*pb.UnsubscribeResponse, error) {
	// Remove subscription from Redis
	pattern := fmt.Sprintf("subscription:%s:*", req.UserId)
	iter := s.rdb.Scan(ctx, 0, pattern, 0).Iterator()
	
	deleted := 0
	for iter.Next(ctx) {
		s.rdb.Del(ctx, iter.Val())
		deleted++
	}
	
	log.Printf("Unsubscribed user %s (%d subscriptions removed)", req.UserId, deleted)
	
	return &pb.UnsubscribeResponse{
		Success: true,
	}, nil
}

func (s *alertServer) PublishAlert(ctx context.Context, req *pb.PublishAlertRequest) (*pb.PublishAlertResponse, error) {
	// Find matching subscriptions and notify
	// Simplified implementation
	log.Printf("Alert published for report: %s", req.Report.Id)
	
	return &pb.PublishAlertResponse{
		SubscribersNotified: 0, // Would implement actual notification logic
	}, nil
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}