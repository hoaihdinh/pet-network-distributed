FROM golang:1.21-alpine AS builder

WORKDIR /app

RUN apk add --no-cache git

COPY ../proto /app/proto
COPY go.mod go.sum ./
RUN go mod download

COPY main.go .

RUN CGO_ENABLED=0 GOOS=linux go build -o service main.go

FROM alpine:latest

RUN apk --no-cache add ca-certificates

WORKDIR /root/

COPY --from=builder /app/service .

EXPOSE 50052

CMD ["./service"]