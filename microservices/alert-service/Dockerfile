FROM golang:1.21-alpine AS builder

WORKDIR /app

RUN apk add --no-cache git

COPY ./proto /app/proto
COPY ./alert-service/go.mod ./alert-service/go.sum ./alert-service/

WORKDIR /app/alert-service

RUN go mod download

COPY ./alert-service/main.go .

RUN CGO_ENABLED=0 GOOS=linux go build -o service main.go

FROM alpine:latest

RUN apk --no-cache add ca-certificates

WORKDIR /root/

COPY --from=builder /app/alert-service/service .

EXPOSE 50054

CMD ["./service"]