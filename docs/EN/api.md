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

## Metrics

```http
GET /metrics
```

Returns Prometheus metrics when `ENABLE_METRICS=true`.

Example:

```bash
curl http://localhost:8000/metrics
```

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
| `query` | Yes | Text query. Must not be empty. |
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

## Image Search

```http
POST /api/v1/search/image
```

Multipart form:

- `file`: image file

Query params:

| Param | Meaning |
|---|---|
| `top_k` | Number of results, 1 to 100. |
| `search_mode` | `ann`, `exact`, or `ann_indexed_only`. |
| `hnsw_ef` | Optional Qdrant HNSW query parameter, 32 to 512. |

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

## Common Status Codes

| Code | Meaning |
|---:|---|
| `200` | Request completed. |
| `202` | Indexing job accepted. |
| `400` | Bad request, invalid query, invalid image, or invalid `top_k`. |
| `401` | Missing or invalid API key. |
| `404` | Images directory or job id not found. |
| `409` | Another indexing job is already queued/running. |
| `413` | Upload exceeds configured byte or pixel limits. |
| `415` | Unsupported upload content type. |
| `500` | Server misconfiguration or unexpected error. |
