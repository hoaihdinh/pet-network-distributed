// microservices/report-service/main.go
package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"net"
	"os"
	"time"

	"github.com/google/uuid"
	_ "github.com/lib/pq"
	"google.golang.org/grpc"
	"google.golang.org/grpc/reflection"
	pb "petnetwork/proto"
)

type reportServer struct {
	pb.UnimplementedReportServiceServer
	db *sql.DB
}

func main() {
	// Database connection
	dbHost := getEnv("DB_HOST", "postgres-reports")
	connStr := fmt.Sprintf(
		"host=%s port=5432 user=petuser password=petpass dbname=pet_reports sslmode=disable",
		dbHost,
	)

	db, err := sql.Open("postgres", connStr)
	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	defer db.Close()

	// Wait for database to be ready
	for i := 0; i < 30; i++ {
		if err := db.Ping(); err == nil {
			break
		}
		log.Printf("Waiting for database... (%d/30)", i+1)
		time.Sleep(2 * time.Second)
	}

	// Initialize schema
	if err := initDB(db); err != nil {
		log.Fatalf("Failed to initialize database: %v", err)
	}

	// Start gRPC server
	port := getEnv("GRPC_PORT", "50051")
	lis, err := net.Listen("tcp", fmt.Sprintf(":%s", port))
	if err != nil {
		log.Fatalf("Failed to listen: %v", err)
	}

	grpcServer := grpc.NewServer()
	pb.RegisterReportServiceServer(grpcServer, &reportServer{db: db})
	reflection.Register(grpcServer) // Enable reflection for grpcurl

	log.Printf("Report Service listening on port %s", port)
	if err := grpcServer.Serve(lis); err != nil {
		log.Fatalf("Failed to serve: %v", err)
	}
}

func initDB(db *sql.DB) error {
	schema := `
	CREATE EXTENSION IF NOT EXISTS postgis;
	
	CREATE TABLE IF NOT EXISTS reports (
		id VARCHAR(36) PRIMARY KEY,
		type VARCHAR(10) NOT NULL,
		pet_type VARCHAR(50) NOT NULL,
		breed VARCHAR(100),
		color VARCHAR(50),
		latitude DOUBLE PRECISION NOT NULL,
		longitude DOUBLE PRECISION NOT NULL,
		address TEXT,
		timestamp BIGINT NOT NULL,
		description TEXT,
		photo_urls TEXT[],
		contact_info VARCHAR(255),
		region VARCHAR(50),
		version BIGINT DEFAULT 1,
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
		updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);

	CREATE INDEX IF NOT EXISTS idx_reports_location 
		ON reports USING GIST (ST_MakePoint(longitude, latitude));
	
	CREATE INDEX IF NOT EXISTS idx_reports_type ON reports(type);
	CREATE INDEX IF NOT EXISTS idx_reports_timestamp ON reports(timestamp DESC);
	CREATE INDEX IF NOT EXISTS idx_reports_region ON reports(region);
	CREATE INDEX IF NOT EXISTS idx_reports_pet_type ON reports(pet_type);
	`

	_, err := db.Exec(schema)
	if err != nil {
		return fmt.Errorf("schema creation failed: %v", err)
	}
	log.Println("Database schema initialized successfully")
	return nil
}

func (s *reportServer) CreateReport(ctx context.Context, req *pb.CreateReportRequest) (*pb.CreateReportResponse, error) {
	reportID := uuid.New().String()
	timestamp := time.Now().Unix()
	region := getEnv("REGION", "us-east")

	query := `
		INSERT INTO reports (id, type, pet_type, breed, color, latitude, longitude, 
							address, timestamp, description, photo_urls, contact_info, region)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
	`

	reportType := "lost"
	if req.Type == pb.ReportType_FOUND {
		reportType = "found"
	}

	_, err := s.db.ExecContext(ctx, query,
		reportID,
		reportType,
		req.PetType,
		req.Breed,
		req.Color,
		req.Location.Latitude,
		req.Location.Longitude,
		req.Location.Address,
		timestamp,
		req.Description,
		req.PhotoUrls,
		req.ContactInfo,
		region,
	)

	if err != nil {
		log.Printf("Error creating report: %v", err)
		return &pb.CreateReportResponse{
			Success: false,
			Message: fmt.Sprintf("Failed to create report: %v", err),
		}, err
	}

	report := &pb.Report{
		Id:          reportID,
		Type:        req.Type,
		PetType:     req.PetType,
		Breed:       req.Breed,
		Color:       req.Color,
		Location:    req.Location,
		Timestamp:   timestamp,
		Description: req.Description,
		PhotoUrls:   req.PhotoUrls,
		ContactInfo: req.ContactInfo,
		Region:      region,
		Version:     1,
	}

	log.Printf("Created report: %s (type: %s, pet: %s)", reportID, reportType, req.PetType)

	return &pb.CreateReportResponse{
		Report:  report,
		Success: true,
		Message: "Report created successfully",
	}, nil
}

func (s *reportServer) GetReport(ctx context.Context, req *pb.GetReportRequest) (*pb.Report, error) {
	query := `
		SELECT id, type, pet_type, breed, color, latitude, longitude, address,
			   timestamp, description, photo_urls, contact_info, region, version
		FROM reports WHERE id = $1
	`

	var report pb.Report
	var reportType string
	var location pb.Location
	var photoURLs []string
	var breed, color, address, description, contactInfo, region sql.NullString

	err := s.db.QueryRowContext(ctx, query, req.Id).Scan(
		&report.Id,
		&reportType,
		&report.PetType,
		&breed,
		&color,
		&location.Latitude,
		&location.Longitude,
		&address,
		&report.Timestamp,
		&description,
		&photoURLs,
		&contactInfo,
		&region,
		&report.Version,
	)

	if err == sql.ErrNoRows {
		return nil, fmt.Errorf("report not found: %s", req.Id)
	}
	if err != nil {
		log.Printf("Error fetching report: %v", err)
		return nil, err
	}

	// Handle nullable fields
	if breed.Valid {
		report.Breed = breed.String
	}
	if color.Valid {
		report.Color = color.String
	}
	if address.Valid {
		location.Address = address.String
	}
	if description.Valid {
		report.Description = description.String
	}
	if contactInfo.Valid {
		report.ContactInfo = contactInfo.String
	}
	if region.Valid {
		report.Region = region.String
	}

	if reportType == "lost" {
		report.Type = pb.ReportType_LOST
	} else {
		report.Type = pb.ReportType_FOUND
	}

	report.Location = &location
	report.PhotoUrls = photoURLs

	return &report, nil
}

func (s *reportServer) ListReports(ctx context.Context, req *pb.ListReportsRequest) (*pb.ListReportsResponse, error) {
	reportType := "lost"
	if req.Type == pb.ReportType_FOUND {
		reportType = "found"
	}

	limit := req.Limit
	if limit == 0 {
		limit = 20
	}

	query := `
		SELECT id, type, pet_type, breed, color, latitude, longitude, address,
			   timestamp, description, photo_urls, contact_info, region, version
		FROM reports 
		WHERE type = $1
		ORDER BY timestamp DESC
		LIMIT $2 OFFSET $3
	`

	rows, err := s.db.QueryContext(ctx, query, reportType, limit, req.Offset)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	var reports []*pb.Report
	for rows.Next() {
		var report pb.Report
		var reportTypeStr string
		var location pb.Location
		var photoURLs []string
		var breed, color, address, description, contactInfo, region sql.NullString

		err := rows.Scan(
			&report.Id,
			&reportTypeStr,
			&report.PetType,
			&breed,
			&color,
			&location.Latitude,
			&location.Longitude,
			&address,
			&report.Timestamp,
			&description,
			&photoURLs,
			&contactInfo,
			&region,
			&report.Version,
		)

		if err != nil {
			log.Printf("Error scanning row: %v", err)
			continue
		}

		// Handle nullable fields
		if breed.Valid {
			report.Breed = breed.String
		}
		if color.Valid {
			report.Color = color.String
		}
		if address.Valid {
			location.Address = address.String
		}
		if description.Valid {
			report.Description = description.String
		}
		if contactInfo.Valid {
			report.ContactInfo = contactInfo.String
		}
		if region.Valid {
			report.Region = region.String
		}

		if reportTypeStr == "lost" {
			report.Type = pb.ReportType_LOST
		} else {
			report.Type = pb.ReportType_FOUND
		}

		report.Location = &location
		report.PhotoUrls = photoURLs
		reports = append(reports, &report)
	}

	// Get total count
	var total int32
	countQuery := "SELECT COUNT(*) FROM reports WHERE type = $1"
	s.db.QueryRowContext(ctx, countQuery, reportType).Scan(&total)

	return &pb.ListReportsResponse{
		Reports: reports,
		Total:   total,
	}, nil
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}