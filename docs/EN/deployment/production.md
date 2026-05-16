# Production Deployment Guide

This guide runs the V3 Docker Compose stack for local production simulation or a
single-VPS deployment.

You can use it in two ways:

- **Local production simulation**: run the production stack on your laptop to
  test the same container layout used on a small VPS.
- **Single-VPS deployment**: copy the repo to a VPS and run the same compose
  stack there.

The stack is not a full cloud platform. It is a single-host container runtime
for the retrieval API, worker, queue, vector database, object storage, and
metrics scraper.

## Services

`docker-compose.prod.yml` starts:

| Service | Purpose |
|---|---|
| `app` | FastAPI API + mounted Gradio UI. |
| `worker` | RQ worker that executes indexing jobs. |
| `redis` | Job queue and job metadata. |
| `qdrant` | Vector database. |
| `minio` | Image object storage. |
| `prometheus` | Metrics scraper. |

## 1. Prepare `.env.production`

```bash
cp .env.production.example .env.production
```

Edit `.env.production`.

### Required Secrets

Generate API key:

```bash
openssl rand -hex 32
```

Set:

```env
ENABLE_API_KEY_AUTH=true
API_KEY=<generated-api-key>
```

Set MinIO credentials. For a simple single-host deployment, use the same root
credentials for the app:

```env
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=<long-password>
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=<long-password>
```

For stricter production, create a separate MinIO app user in the MinIO Console
and put that user's credentials in `MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY`.

### Required Docker-Network Endpoints

Inside production compose, use Docker service names:

```env
QDRANT_URL=http://qdrant:6333
MINIO_ENDPOINT=minio:9000
MINIO_PUBLIC_ENDPOINT=http://localhost:9000
REDIS_URL=redis://redis:6379/0
INDEXING_JOB_BACKEND=redis
```

Do not use `localhost` for these values inside production compose. Inside the
`app` container, `localhost` means the `app` container itself, not Qdrant,
MinIO, or Redis.

`MINIO_PUBLIC_ENDPOINT` is different: it is the endpoint returned inside
presigned image URLs for browsers/API clients. In a local production simulation
use `http://localhost:9000`. On a VPS, use the public MinIO URL or reverse proxy
URL that users can reach.

Production compose publishes MinIO with:

```env
MINIO_API_PORT=9000
MINIO_CONSOLE_PORT=9001
```

The API port must be reachable wherever users open presigned image URLs. The
console port is useful locally, but on a real VPS it should be protected or
kept behind a private network/reverse proxy.

### Data Paths

The production example uses:

```env
LEGACY_IMAGES_PATH=/data/images
LEGACY_INDEX_PATH=/data/embed_data
CAPTIONS_PATH=/data/captions.json
```

These are paths inside the app/worker containers. If you use these paths, make
sure the container can actually access the data, either by extending compose
volumes or copying data into the image/container.

Important: `docker-compose.prod.yml` does not mount your dataset into `/data` by
default. If you want to index host data, add a bind mount or compose override for
both `app` and `worker`, for example:

```yaml
services:
  app:
    volumes:
      - /srv/deepfashion:/data:ro
  worker:
    volumes:
      - /srv/deepfashion:/data:ro
```

With that example, `/srv/deepfashion/images` on the host is visible as
`/data/images` inside the containers.

## 2. Validate Compose Config

```bash
make prod-config
```

Validate with the example file:

```bash
make prod-config PROD_ENV_FILE=.env.production.example
```

## 3. Build And Start

```bash
make prod-build
make prod-up
make prod-logs
```

Open:

- UI: <http://localhost:8000/ui>
- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>
- Metrics: <http://localhost:8000/metrics>
- Prometheus: <http://localhost:9090>

## 4. Verify

The curl examples below use `$API_KEY`. Either export it manually or load it
from `.env.production` first:

```bash
set -a
source .env.production
set +a
```

Health:

```bash
curl http://localhost:8000/health
```

Metrics:

```bash
curl http://localhost:8000/metrics
```

Text search:

```bash
curl -X POST http://localhost:8000/api/v1/search/text \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"query": "red dress", "top_k": 5}'
```

Start indexing:

```bash
curl -X POST http://localhost:8000/api/v1/index/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"images_dir": "/data/images"}'
```

Poll:

```bash
curl -H "X-API-Key: $API_KEY" \
  http://localhost:8000/api/v1/index/<job_id>
```

## 5. Stop

```bash
make prod-down
```

This stops containers but keeps named volumes unless you explicitly remove
volumes.

## VPS Notes

For a real VPS:

- Put the repo under a stable path such as `/srv/clip-fashion-product-retrieval`.
- Keep `.env.production` on the server but outside Git.
- Mount the dataset path into both `app` and `worker` if you want API-triggered
  and worker-triggered indexing to see the same files.
- Use a reverse proxy such as Caddy, Nginx, or Traefik for HTTPS.
- Do not expose MinIO Console publicly without protection.
- If search results return direct MinIO presigned URLs, expose/proxy the MinIO
  API endpoint configured in `MINIO_PUBLIC_ENDPOINT`.
- Back up Qdrant and MinIO volumes.
- Consider firewall rules so only required ports are public.

Minimum public ports:

- `8000` if directly exposing the app, or better only expose reverse proxy
  `80/443`;
- `9090` only if you intentionally expose Prometheus, otherwise keep private;
- MinIO ports should usually stay private unless you know why they must be
  public.

## Troubleshooting

### 401 Unauthorized

The API key is missing or wrong.

Check:

```bash
grep API_KEY .env.production
```

Send:

```bash
-H "X-API-Key: $API_KEY"
```

### App Cannot Connect To Qdrant/MinIO/Redis

Check `.env.production` uses service names:

```env
QDRANT_URL=http://qdrant:6333
MINIO_ENDPOINT=minio:9000
REDIS_URL=redis://redis:6379/0
```

Check containers:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

### Index Job Queued But Not Running

Check worker logs:

```bash
make prod-logs
```

Verify:

```env
INDEXING_JOB_BACKEND=redis
INDEXING_QUEUE_NAME=indexing
```

API and worker must use the same Redis URL and queue name.

### MinIO Login Fails

Use `MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` for the console. Use
`MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` for the app/worker.

For a simple single-host setup, they can be the same pair.

## Release Checklist

Before merging or deploying:

```bash
uv run pytest tests/ -v
uv run ruff check src/ tests/ scripts/
uv run mypy src tests
docker build -t clip-image-retrieval:v3-smoke .
make prod-config
```

Manual smoke checks:

- `/health` returns `status=ok`;
- `/metrics` returns Prometheus output;
- one text search works;
- one image search works;
- one indexing job can be accepted and reaches `completed` or a clearly
  explained `failed`;
- logs include request ids.
