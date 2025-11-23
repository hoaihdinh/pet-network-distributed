FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# copy proto files and app
COPY data_access.proto .
COPY app.py .

# generate gRPC code
RUN python -m grpc_tools.protoc     -I .     --python_out=.     --grpc_python_out=.     data_access.proto

EXPOSE 8082 50051

CMD ["python", "app.py"]