FROM golang:1.21-alpine AS builder

WORKDIR /app

RUN apk add --no-cache git

COPY ./proto /app/proto
COPY ./geo-service/go.mod ./geo-service/go.sum ./geo-service/

WORKDIR /app/geo-service

RUN go mod download

COPY ./geo-service/main.go .

RUN CGO_ENABLED=0 GOOS=linux go build -o service main.go

FROM alpine:latest

RUN apk --no-cache add ca-certificates

WORKDIR /root/

COPY --from=builder /app/geo-service/service .

EXPOSE 50053

CMD ["./service"]