FROM golang:1.21-alpine AS builder

WORKDIR /app

RUN apk add --no-cache git

# Copy proto files first
COPY ../proto /app/proto

# Copy go mod files
COPY go.mod go.sum ./
RUN go mod download

# Copy source
COPY main.go .

# Build
RUN CGO_ENABLED=0 GOOS=linux go build -o service main.go

# Final stage
FROM alpine:latest

RUN apk --no-cache add ca-certificates

WORKDIR /root/

COPY --from=builder /app/service .

EXPOSE 50051

CMD ["./service"]