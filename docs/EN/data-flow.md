# Data Flows

This document explains the main runtime flows through the service.

## 1. Local Development Startup

```mermaid
sequenceDiagram
    autonumber
    participant Dev as Developer
    participant Compose as docker compose
    participant Q as Qdrant
    participant M as MinIO
    participant App as clip-retrieval
    participant Settings as Settings
    participant UI as Gradio UI

    Dev->>Compose: docker compose up -d qdrant minio
    Compose->>Q: start qdrant
    Compose->>M: start minio
    Dev->>App: make run
    App->>Settings: load env + .env
    App->>App: create FastAPI app
    App->>UI: build and mount /ui
    App-->>Dev: listen on localhost:8000
```

Key idea: the Python app runs on the host machine, so it connects to sidecars
through `localhost`.

## 2. Production Stack Startup

```mermaid
sequenceDiagram
    autonumber
    participant Op as Operator
    participant Compose as docker compose prod
    participant Redis as Redis
    participant Q as Qdrant
    participant M as MinIO
    participant App as app container
    participant Worker as worker container
    participant P as Prometheus

    Op->>Compose: make prod-up
    Compose->>Redis: start redis
    Compose->>Q: start qdrant
    Compose->>M: start minio
    Compose->>App: start FastAPI + Gradio
    Compose->>Worker: start RQ worker
    Compose->>P: start prometheus
    P->>App: scrape /metrics
```

Key idea: containers communicate by Docker service name:

- `http://qdrant:6333`
- `minio:9000`
- `redis://redis:6379/0`

## 3. Text Search

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as FastAPI search route
    participant Auth as API key dependency
    participant S as SearchService
    participant E as EmbeddingService
    participant V as Qdrant VectorStore
    participant I as ImageService
    participant M as MinIO ObjectStore

    C->>API: POST /api/v1/search/text
    API->>Auth: verify X-API-Key if enabled
    API->>API: validate TextSearchRequest
    API->>S: search_by_text(query, top_k, mode, hnsw_ef)
    S->>E: get_text_features(query)
    E->>E: lazy-load model if needed
    E->>E: run foreground inference through inference gate
    E-->>S: text vector
    S->>V: search(vector, top_k, mode, hnsw_ef)
    V-->>S: ranked SearchResult rows
    S-->>API: results
    loop each result
        API->>I: get_image_url(image_path)
        I->>M: generate presigned URL
        M-->>I: signed URL
        I-->>API: URL
    end
    API-->>C: SearchResponse
```

Foreground search uses the inference gate with priority over background image
batch indexing.

## 4. Image Search

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as FastAPI image route
    participant Guard as Upload guardrails
    participant PIL as Pillow
    participant S as SearchService
    participant E as EmbeddingService
    participant V as Qdrant
    participant M as MinIO

    C->>API: POST /api/v1/search/image multipart
    API->>Guard: content type and byte limit checks
    API->>PIL: decode image and check pixel limit
    PIL-->>API: RGB image
    API->>S: search_by_image(image, top_k, mode, hnsw_ef)
    S->>E: get_image_features(image)
    E->>E: foreground CLIP inference
    E-->>S: image vector
    S->>V: vector search
    V-->>S: ranked results
    S-->>API: results
    API->>M: generate presigned URLs
    API-->>C: SearchResponse
```

Failure behavior:

- unsupported content type: `415`;
- upload exceeds `MAX_UPLOAD_BYTES`: `413`;
- decoded image exceeds `MAX_IMAGE_PIXELS`: `413`;
- invalid image bytes: `400`.

## 5. Indexing With Memory Backend

Memory backend is mainly for local development.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as Index route
    participant Jobs as IndexingJobBackend(memory)
    participant IX as IndexingService
    participant BG as In-process executor

    C->>API: POST /api/v1/index/
    API->>Jobs: start_indexing_job(images_dir)
    Jobs->>IX: validate/resolve images_dir
    Jobs->>BG: submit job
    Jobs-->>API: queued job snapshot
    API-->>C: 202 + job_id
    BG->>IX: index_directory(images_dir)
    C->>API: GET /api/v1/index/{job_id}
    API->>Jobs: get_indexing_job(job_id)
    Jobs-->>API: latest counters/status
    API-->>C: IndexJobResponse
```

If the API process exits, in-memory job state is lost. That is acceptable for
local development but not ideal for production.

## 6. Indexing With Redis/RQ Backend

Redis backend is the production path.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client or CLI
    participant API as API / clip-index-enqueue
    participant Jobs as IndexingJobBackend(redis)
    participant Redis as Redis
    participant RQ as RQ worker
    participant IX as IndexingService

    C->>API: start indexing
    API->>Jobs: start_indexing_job(images_dir)
    Jobs->>Redis: check active job key
    Jobs->>Redis: write job metadata
    Jobs->>Redis: enqueue RQ job
    Jobs-->>API: queued job snapshot
    API-->>C: job_id + status_url
    Redis-->>RQ: deliver job
    RQ->>IX: index_directory(images_dir)
    IX->>Redis: update progress counters
    IX->>Redis: mark completed or failed
```

Why this matters: the HTTP request finishes quickly. Large indexing work runs in
the worker, so client/proxy timeouts do not kill the request path.

## 7. Incremental Indexing Internals

```mermaid
flowchart TD
    A[Iterate image files] --> B[Build object key images/filename]
    B --> C[Read fast metadata: size and modified time]
    C --> D[Batch get Qdrant payloads]
    D --> E{Payload metadata matches?}
    E -- yes --> F{MinIO object exists?}
    F -- yes --> G[Skip]
    F -- no --> H[Repair: upload only]
    E -- no --> I[Compute SHA256]
    I --> J{content_hash matches?}
    J -- yes --> F
    J -- no --> K[Add to pending batch]
    K --> L[Batch CLIP image embeddings]
    L --> M[Parallel MinIO uploads]
    M --> N[Qdrant upsert batch]
    N --> O[Update job counters]
```

This flow avoids repeated CLIP inference for unchanged images and keeps memory
bounded by batch size.

## 8. CLI Scheduled Ingestion

```mermaid
sequenceDiagram
    autonumber
    participant Cron as cron/systemd/manual shell
    participant CLI as clip-index-enqueue
    participant Jobs as IndexingJobBackend(redis)
    participant Redis as Redis
    participant Worker as RQ worker

    Cron->>CLI: clip-index-enqueue --images-dir /data/images
    CLI->>Jobs: start_indexing_job(path)
    Jobs->>Redis: enqueue job
    CLI-->>Cron: print JSON job_id/status_url
    Redis-->>Worker: job
    Worker->>Worker: run indexing
```

The CLI requires:

```env
INDEXING_JOB_BACKEND=redis
```

## 9. Health And Metrics

`GET /health`:

```mermaid
sequenceDiagram
    participant C as Client
    participant API as Health route
    participant E as EmbeddingService
    participant V as Qdrant
    participant M as MinIO wrapper

    C->>API: GET /health
    API->>E: is_loaded
    API->>V: get_collection_info()
    API->>M: read bucket name
    API-->>C: status/model/qdrant/minio
```

`GET /metrics` returns Prometheus metrics when `ENABLE_METRICS=true`.

Metrics include:

- HTTP request count and latency;
- search latency;
- embedding latency;
- indexing job terminal counts.

## 10. Storage Shape

```mermaid
flowchart LR
    FS["Local file<br/>dress_001.jpg"] --> MinIO["MinIO object<br/>images/dress_001.jpg"]
    FS --> CLIP["CLIP embedding<br/>512-d vector"]
    CLIP --> Qdrant["Qdrant point<br/>id=uuid5(object_key)"]
    Qdrant --> Payload["Payload metadata<br/>image_path, filename, caption,<br/>content_hash, file_size,<br/>modified_at, source_path"]
    Payload --> MinIO
    MinIO --> URL["Presigned URL"]
    URL --> Client["Client browser/API"]
```

Qdrant is the search index. MinIO is the binary image store. The shared key is
`image_path`, which points from Qdrant payload to the MinIO object key.
