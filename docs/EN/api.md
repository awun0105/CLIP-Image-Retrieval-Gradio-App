# API Reference

Interactive API docs are available at:

```text
http://localhost:8000/docs
```

## Authentication

When `ENABLE_API_KEY_AUTH=false`, protected endpoints do not require a key.

When `ENABLE_API_KEY_AUTH=true`, send:

```http
X-API-Key: <API_KEY>
```

Protected route groups:

- `/api/v1/search/*`
- `/api/v1/index/*`

`/health` and `/metrics` are not API-key protected in the current code.

If `ENABLE_API_KEY_AUTH=true` but `API_KEY` is empty, protected endpoints
return `500`. That is treated as a server configuration error, not as a client
authentication failure.

Every response includes an `X-Request-ID` header. If the client sends
`X-Request-ID`, the API reuses it; otherwise the middleware generates one. Use
this value to connect client requests with server logs.

## Health

```http
GET /health
```

Returns service health, model load state, Qdrant collection info, and MinIO
bucket name.

Example:

```bash
curl http://localhost:8000/health
```

Response:

```json
{
  "status": "ok",
  "model_loaded": false,
  "qdrant": {
    "name": "fashion_images",
    "indexed_vectors_count": 10000,
    "points_count": 10000,
    "status": "green",
    "vector_size": 512,
    "distance": "Cosine",
    "segments_count": 3,
    "hnsw_config": {},
    "optimizer_config": {},
    "sample_has_vector": true
  },
  "minio_bucket": "fashion-images"
}
```

`model_loaded=false` is not automatically an error. The CLIP model is lazy
loaded on the first search or indexing request. If the Qdrant probe fails,
`qdrant` contains an `error` field instead of collection details.

## Metrics

```http
GET /metrics
```

Returns Prometheus metrics when `ENABLE_METRICS=true`.

Example:

```bash
curl http://localhost:8000/metrics
```

If `ENABLE_METRICS=false`, this endpoint returns `404`.

Search latency metrics are recorded inside `SearchService`, not only in REST
routes. That means `clip_search_duration_seconds` includes searches triggered
through `/api/v1/search/*` and searches triggered from the mounted Gradio UI.
The histogram measures embedding plus Qdrant retrieval time by `kind`
(`text`/`image`) and search `mode`; it does not include presigned URL response
assembly.

## Text Search

```http
POST /api/v1/search/text
```

Request body:

```json
{
  "query": "red dress",
  "top_k": 5,
  "search_mode": "ann",
  "hnsw_ef": 128
}
```

Fields:

| Field | Required | Meaning |
|---|---:|---|
| `query` | Yes | Text query. Must be 1 to 500 characters. |
| `top_k` | No | Number of results, 1 to 100. Default 5. |
| `search_mode` | No | `ann`, `exact`, or `ann_indexed_only`. Default `ann`. |
| `hnsw_ef` | No | Qdrant query-time HNSW parameter, 32 to 512. |

The API accepts text queries up to 500 characters. CLIP has a smaller token
window than that character limit, so the embedding layer explicitly truncates
long tokenized queries to the model token limit before inference. Keep user
queries concise when evaluating retrieval quality; very long descriptions may
lose trailing details after tokenization.

Example with API key:

```bash
curl -X POST http://localhost:8000/api/v1/search/text \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"query": "red dress", "top_k": 5, "search_mode": "ann"}'
```

Response:

```json
{
  "results": [
    {
      "image_path": "images/example.jpg",
      "image_url": "http://localhost:9000/...",
      "score": 0.73,
      "caption": "...",
      "filename": "example.jpg"
    }
  ],
  "total": 1,
  "query": "red dress"
}
```

If a result's MinIO URL cannot be signed, that result is still returned with
`image_url=null` and the server logs a warning.

## Image Search

```http
POST /api/v1/search/image
```

Multipart form:

- `file`: image file

Query params:

| Param | Required | Meaning |
|---|---:|---|
| `top_k` | No | Number of results, 1 to 100. Default 5. |
| `search_mode` | No | `ann`, `exact`, or `ann_indexed_only`. Default `ann`. |
| `hnsw_ef` | No | Optional Qdrant HNSW query parameter, 32 to 512. |

Example:

```bash
curl -X POST "http://localhost:8000/api/v1/search/image?top_k=5&search_mode=ann" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@/path/to/query.jpg"
```

Upload guardrails:

- unsupported content type returns `415`;
- file larger than `MAX_UPLOAD_BYTES` returns `413`;
- decoded image larger than `MAX_IMAGE_PIXELS` returns `413`;
- invalid image bytes return `400`.

The response shape is the same as text search, except `query` is `null` because
the input was an image upload.

Response:

```json
{
  "results": [
    {
      "image_path": "images/example.jpg",
      "image_url": "http://localhost:9000/...",
      "score": 0.71,
      "caption": "...",
      "filename": "example.jpg"
    }
  ],
  "total": 1,
  "query": null
}
```

## Start Indexing

```http
POST /api/v1/index/
```

Request body:

```json
{
  "images_dir": "/data/images"
}
```

`images_dir` is optional. If omitted, the service uses `LEGACY_IMAGES_PATH`.
The directory path must exist from the API process perspective. In production
compose, that means the path must exist inside the container.

Example:

```bash
curl -X POST http://localhost:8000/api/v1/index/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"images_dir": "/data/images"}'
```

Response:

```json
{
  "job_id": "...",
  "status": "queued",
  "status_url": "/api/v1/index/...",
  "message": "Indexing job accepted"
}
```

The endpoint returns `202 Accepted` because indexing runs as a background job.
If another indexing job is already `queued` or `running`, the endpoint returns
`409`. If `images_dir` does not exist from the API process perspective, it
returns `404`.

## Get Indexing Job

```http
GET /api/v1/index/{job_id}
```

Example:

```bash
curl -H "X-API-Key: $API_KEY" \
  http://localhost:8000/api/v1/index/<job_id>
```

Response:

```json
{
  "job_id": "...",
  "status": "completed",
  "images_dir": "/data/images",
  "indexed_count": 10,
  "updated_count": 2,
  "skipped_count": 100,
  "uploaded_only_count": 1,
  "failed_count": 0,
  "scanned_count": 113,
  "collection_info": {
    "name": "fashion_images",
    "indexed_vectors_count": 10000,
    "points_count": 10000,
    "status": "green",
    "vector_size": 512,
    "distance": "Cosine",
    "segments_count": 3,
    "hnsw_config": {},
    "optimizer_config": {},
    "sample_has_vector": true
  },
  "error": null,
  "created_at": "...",
  "started_at": "...",
  "finished_at": "..."
}
```

`collection_info` is returned only when the job is `completed` or `failed`.
While a job is `queued` or `running`, it is `null` because the collection state
is still changing.

Running response example:

```json
{
  "job_id": "...",
  "status": "running",
  "images_dir": "/data/images",
  "indexed_count": 32,
  "updated_count": 0,
  "skipped_count": 128,
  "uploaded_only_count": 0,
  "failed_count": 0,
  "scanned_count": 200,
  "collection_info": null,
  "error": null,
  "created_at": "...",
  "started_at": "...",
  "finished_at": null
}
```

Important `collection_info` fields:

| Field | Meaning |
|---|---|
| `name` | Qdrant collection name. |
| `indexed_vectors_count` | Number of vectors Qdrant reports as indexed. |
| `points_count` | Number of points in the collection. |
| `status` | Qdrant collection status, usually `green` when healthy. |
| `vector_size` | Vector dimension, expected to be `512` for CLIP ViT-B/16. |
| `distance` | Distance metric, expected to be cosine. |
| `segments_count` | Qdrant segment count, useful for operational checks. |
| `hnsw_config` | Current HNSW collection config reported by Qdrant. |
| `optimizer_config` | Current optimizer config reported by Qdrant. |
| `sample_has_vector` | Whether a sampled point contains a vector payload. |

Job statuses:

- `queued`
- `running`
- `completed`
- `failed`

Unknown `job_id` values return `404`.

## Common Status Codes

| Code | Meaning |
|---:|---|
| `200` | Request completed. |
| `202` | Indexing job accepted. |
| `400` | Runtime bad request, such as invalid image bytes or image-search `top_k` outside `[1, 100]`. |
| `401` | Missing or invalid API key. |
| `404` | Images directory or job id not found. |
| `409` | Another indexing job is already queued/running. |
| `413` | Upload exceeds configured byte or pixel limits. |
| `415` | Unsupported upload content type. |
| `422` | FastAPI/Pydantic validation error, for example empty query, invalid enum, or out-of-range `hnsw_ef`. |
| `500` | Server misconfiguration or unexpected error. |
