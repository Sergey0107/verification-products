# verification-products

## Local launch on macOS

This project is intended to run as a Docker Compose stack.

### Prerequisites

- Docker Desktop for Mac
- At least 8 GB RAM allocated to Docker
- Valid `OPENROUTER_API_KEY` in `app/env/.env`

### Start

From the repository root:

```bash
cd /Users/sergey/Desktop/ivolga
docker compose -f app/docker-compose.yml up --build
```

### Main endpoints

- App UI and API: `http://localhost:8000`
- Extraction service: `http://localhost:8005`
- Prompt registry: `http://localhost:8002`
- Domain analyze: `http://localhost:8003`
- Knowledge base: `http://localhost:8004`
- RabbitMQ management: `http://localhost:15672`
- MinIO API: `http://localhost:9000`
- MinIO console: `http://localhost:9001`

### Notes

- Local object storage is provided by MinIO. The bucket is created automatically on startup.
- The current extraction baseline is `openrouter` only.
- `docling_local` and `docling_remote` remain in the API contract as disabled stubs for future re-enable.
- The comparison flow requires `OPENROUTER_API_KEY` in `app/env/.env`.
- The extraction service uses the local `/Users/sergey/Desktop/ivolga/extraction` folder as its Docker build context.
- The analysis detail page now includes a built-in document viewer for compliance review. It uses normalized evidence payloads linked to each `ComparisonRow`.

### Evidence navigation payload

- `GET /api/analyses/{analysis_id}/viewer-context`
- Returns `documents` / `available_documents` (`tz`, `passport`) and `rows` with `tz_evidence` / `passport_evidence`
- Each evidence payload contains:
  - `evidence_version`
  - `position_status`
  - `locator_strategy`
  - `display_quote`
  - `full_quote`
  - `fallback_quote`
  - `matched_terms`
  - `confidence`
  - `source_spans`
  - `page_anchors`
  - `active_span`
  - `exact_span`
  - `text_anchor`
  - `page_anchor`
  - `navigation_target`

### Current limitations

- The current viewer uses `PDF.js` for page-level rendering and overlay highlighting when `bbox` exists.
- Current positioning quality still depends on extraction references. If only quote text is available, the UI falls back to text/page anchors without exact coordinates.
- `bbox` precision is only as good as upstream extraction. The current pipeline accepts exact span data, but many documents will still remain in fallback/degraded mode until extraction improves.

### Health endpoints

- `http://localhost:8000/health`
- `http://localhost:8001/health`
- `http://localhost:8002/health`
- `http://localhost:8003/health`
- `http://localhost:8004/health`
- `http://localhost:8005/health`
