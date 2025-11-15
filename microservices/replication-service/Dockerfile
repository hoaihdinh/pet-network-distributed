FROM golang:1.21-alpine AS builder

WORKDIR /app

RUN apk add --no-cache git

COPY ./proto /app/proto
COPY ./replication-service/go.mod ./replication-service/go.sum ./replication-service/

WORKDIR /app/replication-service

RUN go mod download

COPY ../replication-service/main.go .

RUN CGO_ENABLED=0 GOOS=linux go build -o service main.go

FROM alpine:latest

RUN apk --no-cache add ca-certificates

WORKDIR /root/

COPY --from=builder /app/replication-service/service .

EXPOSE 50055

CMD ["./service"]