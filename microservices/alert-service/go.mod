module petnetwork/alert-service

go 1.21

require (
	github.com/go-redis/redis/v8 v8.11.5
	google.golang.org/grpc v1.60.1
	petnetwork/proto v0.0.0
)

replace petnetwork/proto => ../proto

require (
	github.com/cespare/xxhash/v2 v2.2.0 // indirect
	github.com/dgryski/go-rendezvous v0.0.0-20200823014737-9f7001d12a5f // indirect
	github.com/golang/protobuf v1.5.3 // indirect
	golang.org/x/net v0.20.0 // indirect
	golang.org/x/sys v0.16.0 // indirect
	golang.org/x/text v0.14.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20240116215550-a9fa1716bcac // indirect
	google.golang.org/protobuf v1.32.0 // indirect
)
