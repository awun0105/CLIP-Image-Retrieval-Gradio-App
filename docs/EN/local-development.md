# Local Development Guide

Use local development mode when you are coding, debugging, or testing manually
on your laptop.

In this mode:

```text
FastAPI/Gradio app runs directly on your machine
Qdrant and MinIO run in Docker
Config is loaded from .env
API key auth is usually disabled
```

## Prerequisites

- Python 3.10+
- Docker and Docker Compose
- `uv`
- `make`

## Setup

Install dependencies:

```bash
make dev
```

Create local config:

```bash
cp .env.example .env
```

Start sidecars:

```bash
docker compose up -d qdrant minio
```

This starts only the sidecars. Do not use `make docker-up` for this host-run
workflow unless you intentionally want the app container too; otherwise the
containerized app can compete with `make run` for port `8000`.

Run the app:

```bash
make run
```

Open:

- UI: <http://localhost:8000/ui>
- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>
- Metrics: <http://localhost:8000/metrics> (Raw data)
- MinIO Console: <http://localhost:9001>

*Note: The Prometheus dashboard (port 9090) is only included in the [Production Stack](deployment/production.md).*

Default MinIO credentials from `docker-compose.yml`:

```text
username: minioadmin
password: minioadmin
```

## Why Local Uses localhost

The Python app runs on the host machine, not inside Docker. Therefore the app
connects to sidecars through host ports:

```env
QDRANT_URL=http://localhost:6333
MINIO_ENDPOINT=localhost:9000
```

This is different from production compose, where all services run inside the
same Docker network and use service names such as `qdrant:6333` and
`minio:9000`.

If you enable API key auth locally, add `-H "X-API-Key: $API_KEY"` to the curl
examples below.

If you set `QDRANT_MODE=memory`, the app uses an in-process Qdrant instance and
does not need the Qdrant sidecar. MinIO is still required because search results
return MinIO presigned URLs.

## Index A Folder

If API key auth is disabled:

```bash
curl -X POST http://localhost:8000/api/v1/index/ \
  -H "Content-Type: application/json" \
  -d '{"images_dir": "./DeepFashion/images"}'
```

The response contains a `job_id` and `status_url`:

```json
{
  "job_id": "...",
  "status": "queued",
  "status_url": "/api/v1/index/...",
  "message": "Indexing job accepted"
}
```

Poll:

```bash
curl http://localhost:8000/api/v1/index/<job_id>
```

## Search

Text search:

```bash
curl -X POST http://localhost:8000/api/v1/search/text \
  -H "Content-Type: application/json" \
  -d '{"query": "red dress", "top_k": 5}'
```

Image search:

```bash
curl -X POST "http://localhost:8000/api/v1/search/image?top_k=5" \
  -F "file=@/path/to/query.jpg"
```

## Run Checks

```bash
uv run pytest tests/ -v
uv run ruff check src/ tests/ scripts/
uv run mypy src tests
```

Build smoke test:

```bash
docker build -t clip-image-retrieval:v3-smoke .
```

## Common Local Problems

### Qdrant Connection Fails

Check that Qdrant is running:

```bash
docker compose ps qdrant
curl http://localhost:6333
```

### MinIO Connection Fails

Check that MinIO is running:

```bash
docker compose ps minio
curl http://localhost:9000/minio/health/live
```

Verify `.env`:

```env
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
```

### First Search Is Slow

This is expected. `EmbeddingService` lazy-loads the CLIP model on first use.
After the model is loaded, later requests are faster.

### Indexing Says Job Already Running

Only one indexing job can run at a time. Poll the current job or wait for it to
finish. This avoids conflicting writes and protects CLIP/MinIO/Qdrant from
unbounded concurrent ingestion work.

### Indexed Results Show Broken Image URLs

Check that `MINIO_ENDPOINT` is reachable from your browser. In local host-run
mode it should usually be:

```env
MINIO_ENDPOINT=localhost:9000
MINIO_PUBLIC_ENDPOINT=http://localhost:9000
```

If you accidentally use `minio:9000` while running the Python app on the host,
the browser will receive presigned URLs pointing to a Docker-only hostname.
