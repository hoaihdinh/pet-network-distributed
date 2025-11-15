FROM golang:1.21-alpine AS builder

WORKDIR /app

RUN apk add --no-cache git

COPY ./proto /app/proto
COPY ./matching-service/go.mod ./matching-service/go.sum ./matching-service/

WORKDIR /app/matching-service

RUN go mod download

COPY ./matching-service/main.go .

RUN CGO_ENABLED=0 GOOS=linux go build -o service main.go

FROM alpine:latest

RUN apk --no-cache add ca-certificates

WORKDIR /root/

COPY --from=builder /app/matching-service/service .

EXPOSE 50052

CMD ["./service"]