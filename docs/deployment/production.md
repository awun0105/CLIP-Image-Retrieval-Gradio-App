# Production Deployment Guide

This guide describes the minimum production deployment for the V3 Docker
Compose stack.

## 1. Prepare Environment

```bash
cp .env.production.example .env.production
```

Edit `.env.production` and replace:

- `API_KEY`
- `MINIO_ACCESS_KEY`
- `MINIO_SECRET_KEY`
- `MINIO_ROOT_USER`
- `MINIO_ROOT_PASSWORD`
- data paths such as `LEGACY_IMAGES_PATH`, `LEGACY_INDEX_PATH`, and
  `CAPTIONS_PATH`

Do not commit `.env.production`.

## 2. Validate Compose Config

```bash
make prod-config
```

For validation against the example file:

```bash
make prod-config PROD_ENV_FILE=.env.production.example
```

## 3. Start Production Stack

```bash
make prod-build
make prod-up
make prod-logs
```

Services:

- `app`: FastAPI + Gradio UI
- `worker`: RQ indexing worker
- `redis`: durable job queue and job metadata
- `qdrant`: vector database
- `minio`: image object storage
- `prometheus`: metrics scraper

## 4. Verify Deployment

```bash
curl http://localhost:8000/health
curl http://localhost:8000/metrics
```

Search with API key:

```bash
curl -X POST http://localhost:8000/api/v1/search/text \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"query": "red dress", "top_k": 5}'
```

Enqueue indexing:

```bash
uv run clip-index-enqueue --images-dir /data/images
```

Or through the API:

```bash
curl -X POST http://localhost:8000/api/v1/index/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"images_dir": "/data/images"}'
```

Poll job status:

```bash
curl -H "X-API-Key: $API_KEY" http://localhost:8000/api/v1/index/<job_id>
```

## 5. Rollback

Use one change at a time:

1. Stop the stack: `make prod-down`.
2. Restore the previous image/tag or previous commit.
3. Restore Qdrant/MinIO volumes if the deployment changed persisted data.
4. Start the stack: `make prod-up`.
5. Re-run `/health`, one search request, and one indexing status check.

## 6. Release Checklist

- `uv run ruff check src/ tests/ scripts/`
- `uv run mypy src tests`
- `uv run pytest tests/ -v`
- `make prod-config`
- Docker image builds successfully.
- `/health` returns `status=ok`.
- `/metrics` is reachable from Prometheus.
- One indexing job can be enqueued and completed.
- Text search and image search work with `X-API-Key`.
- Logs include request ids.
