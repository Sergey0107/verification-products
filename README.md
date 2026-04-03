# verification-products

## Local launch on macOS

This project is intended to run as a Docker Compose stack.

### Prerequisites

- Docker Desktop for Mac
- At least 8 GB RAM allocated to Docker

### Start

From the repository root:

```bash
cd /Users/sergey/Desktop/ivolga
docker compose -f app/docker-compose.yml up --build
```

### Main endpoints

- App UI and API: `http://localhost:8000`
- RabbitMQ management: `http://localhost:15672`
- MinIO API: `http://localhost:9000`
- MinIO console: `http://localhost:9001`

### Notes

- Local object storage is provided by MinIO. The bucket is created automatically on startup.
- The comparison flow requires `OPENROUTER_API_KEY` in `app/env/.env`.
- The extraction service uses the local `extraction` folder as its Docker build context.
