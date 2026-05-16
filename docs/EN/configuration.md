# Configuration Guide

The service uses `pydantic-settings` in `src/config.py`. Values come from
environment variables and, when present, a local `.env` file.

Runtime precedence is:

1. environment variables already present in the process or container;
2. values from `.env` when the app is run directly from the repository;
3. defaults declared in `src/config.py`.

Unknown environment variables are ignored. Boolean values can be written as
`true`/`false`. Empty optional values such as `DEVICE=` or `QDRANT_API_KEY=`
mean "not configured".

## Which Env File Should I Use?

| File | Used When | How To Use |
|---|---|---|
| `.env.example` | Starting local development | Copy to `.env`, then edit local values if needed. |
| `.env` | Running the app directly with `make run` | Loaded automatically by `Settings`. Keep it local to your machine. |
| `.env.production.example` | Preparing Docker production stack config | Copy to `.env.production`, then replace secrets and deployment paths. |
| `.env.production` | Running `docker-compose.prod.yml` | Passed to Compose by `make prod-*` targets. Keep it local to the server. |

Do not commit `.env` or `.env.production`.

`docker-compose.yml` is the simple local Compose stack. Its app service uses
inline development defaults and is mainly for quick demos. `docker-compose.prod.yml`
uses `env_file` and should be used when you want to simulate or run the
production stack.

## Local Development vs Production Stack

### Local Development

Use this when you are coding on your laptop.

```text
Python app runs on host machine
Qdrant and MinIO run in Docker
```

Endpoints usually use `localhost`:

```env
QDRANT_URL=http://localhost:6333
MINIO_ENDPOINT=localhost:9000
REDIS_URL=redis://localhost:6379/0
```

API key auth is usually disabled for convenience:

```env
ENABLE_API_KEY_AUTH=false
```

### Production Stack

Use this when running all services through Docker Compose, either locally as a
VPS simulation or on an actual VPS.

```text
app container
worker container
redis container
qdrant container
minio container
prometheus container
```

Containers call each other by Docker service name:

```env
QDRANT_URL=http://qdrant:6333
MINIO_ENDPOINT=minio:9000
REDIS_URL=redis://redis:6379/0
```

API key auth should be enabled:

```env
ENABLE_API_KEY_AUTH=true
```

## Where Do Credentials Come From?

### API Key

`API_KEY` is an application-level shared secret. You create it yourself.

Generate one:

```bash
openssl rand -hex 32
```

Set it:

```env
ENABLE_API_KEY_AUTH=true
API_KEY=<generated-value>
```

Clients must send:

```http
X-API-Key: <generated-value>
```

### MinIO Credentials

This project self-hosts MinIO in Docker Compose. That means you choose the
credentials.

For a simple production-stack demo, you can use the same root credentials for
the app:

```env
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=change-this-password
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=change-this-password
```

For a stricter deployment, create a separate app user in the MinIO Console and
use that user's access key and secret key as:

```env
MINIO_ACCESS_KEY=<app-user-access-key>
MINIO_SECRET_KEY=<app-user-secret-key>
```

`MINIO_ROOT_USER` and `MINIO_ROOT_PASSWORD` are used by the MinIO server itself.
`MINIO_ACCESS_KEY` and `MINIO_SECRET_KEY` are used by the app and worker to
connect to MinIO.

## Configuration Groups

### Model

| Variable | Default | Meaning |
|---|---|---|
| `MODEL_ID` | `anhquanlam/clip-finetuned-deepfashion` | Hugging Face model id loaded by `EmbeddingService`. |
| `DEVICE` | empty | If empty, auto-selects `cuda` when available, otherwise `cpu`. Set to `cpu` to force CPU. |

The Docker production image currently uses CPU PyTorch wheels for smaller and
more reliable builds. For real GPU serving, add a GPU-specific image/profile or
move inference to a model server such as Triton or TorchServe.

### API And Security

| Variable | Default | Meaning |
|---|---|---|
| `API_HOST` | `0.0.0.0` | Host address for uvicorn. |
| `API_PORT` | `8000` | API port. |
| `ENABLE_API_KEY_AUTH` | `false` | When true, protected routes require `X-API-Key`. |
| `API_KEY` | empty | Shared API secret. Required if auth is enabled. |
| `MAX_UPLOAD_BYTES` | `104857600` | Max upload size for image search. `0` disables byte limit. |
| `MAX_IMAGE_PIXELS` | `50000000` | Max decoded image dimensions as `width * height`. `0` disables pixel limit. |
| `ALLOWED_IMAGE_CONTENT_TYPES` | `image/jpeg,image/png,image/webp` | Allowed upload content types. |

Upload guardrails protect the service from accidental huge files and basic
abuse. They are configurable so high-quality images can still be allowed.

### Qdrant

| Variable | Default | Meaning |
|---|---|---|
| `QDRANT_MODE` | `memory` | `memory`, `local`, or `remote`. |
| `QDRANT_PATH` | `./qdrant_data` | Local file path when using local mode. |
| `QDRANT_URL` | `http://localhost:6333` | Remote Qdrant URL. In production compose use `http://qdrant:6333`. |
| `QDRANT_API_KEY` | empty | Optional API key for secured Qdrant. |
| `QDRANT_COLLECTION` | `fashion_images` | Collection name. |
| `QDRANT_HNSW_EF` | `128` | Query-time HNSW accuracy/speed parameter. Higher can improve recall but may increase latency. |
| `QDRANT_INDEXING_THRESHOLD` | `5000` | Qdrant optimizer threshold for vector indexing. |
| `QDRANT_FULL_SCAN_THRESHOLD` | `5000` | Qdrant HNSW config threshold for full scan behavior. |
| `QDRANT_UPSERT_BATCH_SIZE` | `100` | Number of Qdrant points sent per upsert request. This is separate from `INGEST_BATCH_SIZE`, which controls CLIP image encoding batches. |
| `SEARCH_MODE_DEFAULT` | `ann` | Default search mode: `ann`, `exact`, or `ann_indexed_only`. |

Qdrant mode decides which connection settings matter:

- `memory`: in-process Qdrant used mainly by tests and isolated local runs;
  `QDRANT_URL` and `QDRANT_PATH` are ignored.
- `local`: local embedded Qdrant storage at `QDRANT_PATH`; useful only when you
  want file-backed local storage without a Qdrant server.
- `remote`: connect to a Qdrant server through `QDRANT_URL` and optional
  `QDRANT_API_KEY`; this is the normal Docker and production mode.

Use `QDRANT_UPSERT_BATCH_SIZE` to tune write pressure on Qdrant. Larger values
reduce the number of upsert calls but increase request size and memory held
while building point payloads. Keep it independent from `INGEST_BATCH_SIZE`,
which tunes CLIP inference throughput and image memory pressure.

Search modes:

- `ann`: approximate nearest neighbor search using Qdrant index when available.
- `exact`: exact full scan; useful as a quality baseline.
- `ann_indexed_only`: search indexed segments only; useful when you want to
  avoid non-indexed data during index build phases.

### MinIO

| Variable | Default | Meaning |
|---|---|---|
| `MINIO_ENDPOINT` | `localhost:9000` | MinIO API endpoint. In production compose use `minio:9000`. |
| `MINIO_ACCESS_KEY` | `minioadmin` | Credential used by app/worker. |
| `MINIO_SECRET_KEY` | `minioadmin` | Credential used by app/worker. |
| `MINIO_BUCKET` | `fashion-images` | Bucket containing indexed images. |
| `MINIO_SECURE` | `false` | Use HTTPS when true. |
| `MINIO_PUBLIC_ENDPOINT` | unset | Optional browser/client-facing MinIO endpoint used when rewriting presigned URLs. |
| `MINIO_REGION` | `us-east-1` | S3 signing region for MinIO presigned URLs. |
| `MINIO_API_PORT` | production example only | Host port published by production compose for MinIO API/presigned URLs. |
| `MINIO_CONSOLE_PORT` | production example only | Host port published by production compose for MinIO Console. |
| `MINIO_ROOT_USER` | production example only | Root user for MinIO container. |
| `MINIO_ROOT_PASSWORD` | production example only | Root password for MinIO container. |

MinIO stores image files. Qdrant stores vectors and metadata. Search results use
Qdrant payloads to find MinIO object keys and then return presigned URLs.

`MINIO_ENDPOINT` is the internal endpoint used by the app/worker SDK. In
production compose this is usually `minio:9000`. Browser clients normally
cannot resolve that Docker-only hostname, so set `MINIO_PUBLIC_ENDPOINT` to the
public endpoint users can open, for example `http://localhost:9000` during a
local production simulation or `https://minio.example.com` on a VPS behind a
reverse proxy.

When `MINIO_PUBLIC_ENDPOINT` is set, the application still uses
`MINIO_ENDPOINT` for internal storage operations, but it creates presigned URLs
with a separate MinIO client pointed at the public endpoint. This avoids
returning Docker-only URLs such as `http://minio:9000/...` to browsers or
external API clients.

### Redis/RQ Indexing Jobs

| Variable | Default | Meaning |
|---|---|---|
| `INDEXING_JOB_BACKEND` | `memory` | `memory` for local in-process jobs, `redis` for Redis/RQ jobs. |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection URL. In production compose use `redis://redis:6379/0`. |
| `INDEXING_QUEUE_NAME` | `indexing` | RQ queue name. |
| `INDEXING_JOB_TIMEOUT_SECONDS` | `3600` | Max runtime for a queued RQ job. |
| `INDEXING_JOB_RESULT_TTL_SECONDS` | `86400` | How long successful RQ results stay in Redis. |
| `INDEXING_JOB_FAILURE_TTL_SECONDS` | `604800` | How long failed RQ job data stays in Redis. |

Use `memory` for local development if you do not want to run Redis. Use `redis`
for production so indexing can run in the worker container and survive API
process restarts better than in-memory state.

When `INDEXING_JOB_BACKEND=redis`, the API and worker must use the same
`REDIS_URL` and `INDEXING_QUEUE_NAME`. If they differ, jobs can be accepted by
the API but never picked up by the worker.

The application uses Redis' default byte-response mode for compatibility with
RQ. Job payloads are JSON strings decoded by the application code. There is no
environment variable to change that behavior; avoid adding client-side
`decode_responses=true` when extending Redis/RQ code because RQ expects byte
payloads internally.

### Indexing Performance

| Variable | Default | Meaning |
|---|---|---|
| `INGEST_BATCH_SIZE` | `32` | Number of changed/new images encoded per CLIP batch. |
| `MINIO_UPLOAD_WORKERS` | `8` | Number of parallel upload workers during batch flush. |
| `INDEX_FAST_METADATA_SKIP` | `true` | Skip SHA256 when metadata already proves file is unchanged. |
| `INDEX_REPAIR_MISSING_OBJECTS` | `true` | Re-upload missing MinIO objects without re-encoding when Qdrant vector is still valid. |

Batching improves CLIP throughput and limits memory pressure. Upload workers
improve network I/O throughput but should not be set so high that MinIO or the
host becomes overloaded. Qdrant write chunking is configured in the Qdrant
section through `QDRANT_UPSERT_BATCH_SIZE`.

### Observability

| Variable | Default | Meaning |
|---|---|---|
| `LOG_LEVEL` | `INFO` | Python root log level. |
| `LOG_FORMAT` | `text` | `text` or `json`. Use `json` in production. |
| `ENABLE_METRICS` | `true` | Enable `/metrics`. |

### Data Paths

| Variable | Default | Meaning |
|---|---|---|
| `LEGACY_IMAGES_PATH` | `./DeepFashion/images` | Default image folder for indexing when request omits `images_dir`. |
| `LEGACY_INDEX_PATH` | `./DeepFashion/embed_data` | Legacy embedding path used by migration tools. |
| `CAPTIONS_PATH` | `./DeepFashion/captions.json` | Optional captions JSON used during indexing/migration. |

In production compose, paths refer to paths inside the container, for example
`/data/images`. You must mount or copy data so the container can actually see
that path.

`LEGACY_IMAGES_PATH` is named "legacy" because it came from the original
DeepFashion migration flow, but in the current API it also acts as the default
indexing folder when `POST /api/v1/index/` omits `images_dir`.

`CAPTIONS_PATH` currently points to a JSON object loaded into worker memory
during indexing/migration. This is simple and fast for moderate metadata files.
For very large catalogs, treat caption lookup as the next ingestion hardening
task: move captions to SQLite, JSONL with an index, or a key-value store so the
worker can look up captions lazily by filename instead of parsing the entire map
before each run.
