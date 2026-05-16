# Operations Guide

This document explains how to inspect and operate the service once it is
running.

## Health

```bash
curl http://localhost:8000/health
```

Health includes:

- `status`: high-level API status;
- `model_loaded`: whether CLIP has been loaded;
- `qdrant`: collection state;
- `minio_bucket`: configured bucket name.

Important note: `model_loaded=false` does not necessarily mean failure. The
model is lazy-loaded and may remain unloaded until the first search or indexing
job.

## Metrics

```bash
curl http://localhost:8000/metrics
```

Prometheus scrapes the same endpoint in production compose.

**Note on availability:** The `/metrics` endpoint returns Prometheus text when
`ENABLE_METRICS=true`. If `ENABLE_METRICS=false`, it returns `404`. The
Prometheus dashboard on port `9090` is only started as part of the
[Production Stack](deployment/production.md). In local development, verify raw
metrics data by visiting `http://localhost:8000/metrics`.

Important metric groups:

| Metric | Meaning |
|---|---|
| `clip_http_requests_total` | Count of HTTP requests by method, route, status. |
| `clip_http_request_duration_seconds` | HTTP latency histogram. |
| `clip_search_duration_seconds` | Search latency by text/image and search mode. Recorded in `SearchService`, so both REST API and Gradio UI searches are included. |
| `clip_embedding_duration_seconds` | CLIP inference latency by kind and foreground/background priority. |
| `clip_indexing_jobs_total` | Completed/failed indexing job count. |

## Logs

Local development usually uses text logs:

```env
LOG_FORMAT=text
```

Production should use JSON logs:

```env
LOG_FORMAT=json
```

Each request gets a request id. The response includes:

```http
X-Request-ID: ...
```

The same id appears in logs, which helps connect a user request to backend
events.

## Indexing Jobs

Start:

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

Status values:

- `queued`: accepted but not running yet;
- `running`: worker or local executor is processing;
- `completed`: terminal success;
- `failed`: terminal failure, inspect `error` and worker logs.

Counters:

- `scanned_count`: files inspected;
- `indexed_count`: new files inserted;
- `updated_count`: changed files updated;
- `skipped_count`: unchanged files skipped;
- `uploaded_only_count`: MinIO repaired without re-embedding;
- `failed_count`: per-file failures.

Memory note: indexing currently loads `CAPTIONS_PATH` as a single JSON object
when that file exists. If the worker uses unexpectedly high memory before CLIP
encoding starts, inspect the captions file size first. For very large catalogs,
the recommended next hardening task is to replace full JSON loading with lazy
caption lookup through SQLite, indexed JSONL, or a key-value store.

## Common Incidents

### API Returns 401

Cause: API key auth is enabled and the request is missing or using the wrong
key.

Check:

```env
ENABLE_API_KEY_AUTH=true
API_KEY=...
```

Send:

```bash
-H "X-API-Key: $API_KEY"
```

### Indexing Returns 409

Cause: one indexing job is already queued or running.

Action:

1. Poll the current job if you know the id.
2. Check worker logs.
3. Wait for completion or failure.

This is intentional to prevent multiple heavy ingestion jobs from competing for
CLIP, Qdrant, and MinIO.

### Job Is Queued But Not Running

Likely causes:

- worker container is not running;
- `INDEXING_JOB_BACKEND` is not `redis`;
- API and worker use different `REDIS_URL` or queue name.
- the job was enqueued from the host using a container-only Redis URL such as
  `redis://redis:6379/0`.

Check:

```bash
docker compose -f docker-compose.prod.yml ps
make prod-logs
```

If you run `clip-index-enqueue` from the host, use a host-reachable Redis URL
such as `redis://localhost:6379/0`. Inside production compose, use
`redis://redis:6379/0`.

### Search Works But Images Do Not Load

Likely causes:

- MinIO object is missing;
- presigned URL points to an endpoint not reachable by the browser;
- bucket credentials are wrong.

Actions:

1. Open MinIO Console.
2. Check bucket exists.
3. Check object key from `image_path`.
4. Check `MINIO_PUBLIC_ENDPOINT`. In production compose the internal endpoint is
   usually `minio:9000`, but browsers need a reachable endpoint such as
   `http://localhost:9000` for local simulation or a public reverse-proxy URL on
   a VPS.
5. Re-run indexing; missing objects can be repaired if Qdrant metadata is valid.

### First Request Is Slow

The CLIP model is lazy-loaded on first use. This can take time because the model
must be downloaded/loaded and moved to CPU/GPU.

For demos, run one warm-up text search before showing the app.
