# Data flows

This document shows every end-to-end data path through the service using
Mermaid sequence and flow diagrams. They cover:

1. [Process startup & dependency wiring](#1-process-startup--dependency-wiring)
2. [Text search](#2-text-search)
3. [Image search](#3-image-search)
4. [Indexing a directory](#4-indexing-a-directory)
5. [Health probe](#5-health-probe)
6. [Migration from legacy artefacts](#6-migration-from-legacy-artefacts)
7. [Gradio UI interactions](#7-gradio-ui-interactions)
8. [Storage shape](#8-storage-shape)

---

## 1) Process startup & dependency wiring

```mermaid
sequenceDiagram
    autonumber
    participant OS as OS / Docker
    participant Server as server.main()
    participant Settings as Settings (pydantic)
    participant DI as dependencies.get_*()
    participant App as FastAPI (create_app)
    participant UI as Gradio (build_ui)
    participant U as uvicorn

    OS->>Server: invoke `clip-retrieval`
    Server->>Settings: get_settings()
    Settings-->>Server: Settings(env + .env)
    Server->>App: create_app()
    App-->>Server: FastAPI app (CORS + routers)
    Server->>DI: get_search_service(), get_image_service()
    DI->>DI: build EmbeddingService, VectorStore, ObjectStore (lazy)
    DI-->>Server: services
    Server->>UI: build_ui(search_service, image_service)
    UI-->>Server: Gradio Blocks
    Server->>App: gr.mount_gradio_app(app, ui, "/ui")
    Server->>U: uvicorn.run(app, host, port)
    U-->>OS: listen on :8000
```

Notes:

- `@lru_cache(maxsize=1)` on every `get_*` factory makes each service a
  process-wide singleton.
- `EmbeddingService` does **not** load the CLIP model here — it waits until
  the first call to `get_text_features` / `get_image_features`.

---

## 2) Text search

`POST /api/v1/search/text` with `{ "query": "...", "top_k": N }`.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as FastAPI route
    participant S as SearchService
    participant E as EmbeddingService
    participant V as VectorStore (Qdrant)
    participant I as ImageService
    participant M as ObjectStore (MinIO)

    C->>API: POST /api/v1/search/text
    API->>API: validate via TextSearchRequest
    API->>S: search_by_text(query, top_k)
    S->>S: reject empty/whitespace query (400)
    S->>E: get_text_features(query)
    E->>E: _ensure_loaded() (first call only)
    E-->>S: np.ndarray (1, 512)
    S->>V: search(vector, top_k)
    V->>V: query_points(hnsw_ef=128, cosine)
    V-->>S: list[dict{image_path, score, caption, filename}]
    S-->>API: list[SearchResult]
    loop each result
        API->>I: get_image_url(image_path)
        I->>M: presigned_get_object(bucket, key)
        M-->>I: signed URL
        I-->>API: URL
    end
    API-->>C: SearchResponse(results=[…], total, query)
```

---

## 3) Image search

`POST /api/v1/search/image` with multipart `file` + query param `top_k`.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as FastAPI route
    participant P as PIL.Image
    participant S as SearchService
    participant E as EmbeddingService
    participant V as VectorStore
    participant I as ImageService
    participant M as ObjectStore

    C->>API: POST /api/v1/search/image (multipart)
    API->>API: validate top_k ∈ [1, 100]
    API->>P: Image.open(BytesIO(bytes)).convert("RGB")
    P-->>API: PIL.Image
    API->>S: search_by_image(image, top_k)
    S->>E: get_image_features(image)
    E-->>S: np.ndarray (1, 512)
    S->>V: search(vector, top_k)
    V-->>S: list[dict]
    S-->>API: list[SearchResult]
    loop each result
        API->>I: get_image_url(image_path)
        I->>M: presigned_get_object(bucket, key)
        M-->>I: URL
        I-->>API: URL
    end
    API-->>C: SearchResponse
```

---

## 4) Indexing a directory

`POST /api/v1/index/` with `{ "images_dir": "/path" }` starts a background
indexing job (optional path — falls back to `LEGACY_IMAGES_PATH`). The response
contains a `job_id`; call `GET /api/v1/index/{job_id}` to poll status.

```mermaid
flowchart TD
    A[POST /api/v1/index/] --> B{images_dir provided?}
    B -- yes --> C[Use request.images_dir]
    B -- no --> D[Fallback to settings.legacy_images_path]
    C --> E{dir exists?}
    D --> E
    E -- no --> F[HTTP 404]
    E -- yes --> R[Create background job]
    R --> S[Return 202 + job_id]
    R -. worker thread .-> G[Load captions.json if present]
    G --> H[Iterate *.jpg/jpeg/png]
    H --> I[Check Qdrant payload + MinIO object state]
    I -- unchanged --> J[Skip]
    I -- missing object only --> K[Upload repair without re-encoding]
    I -- new or changed --> L[Batch CLIP image embedding]
    L --> M[Parallel MinIO uploads]
    M --> N[Qdrant upsert per ingest batch]
    N --> O[Update job counters]
    O --> P[Job completed or failed]
```

The detailed sequence between services:

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as FastAPI route
    participant JOB as Indexing job registry
    participant IX as IndexingService
    participant FS as Local filesystem
    participant E as EmbeddingService
    participant M as ObjectStore (MinIO)
    participant V as VectorStore (Qdrant)

    C->>API: POST /api/v1/index/
    API->>IX: start_indexing_job(path)
    IX->>JOB: create queued job
    IX-->>API: job_id
    API-->>C: IndexStartResponse(status=queued, job_id)
    IX->>IX: background worker runs index_directory(path)
    IX->>FS: scan *.jpg/jpeg/png
    loop each ingest batch
        IX->>V: get_payloads(point_ids)
        V-->>IX: metadata
        IX->>M: object_exists(images/<name>)
        M-->>IX: exists?
        IX->>E: get_image_batch_features(images)
        E-->>IX: vectors
        IX->>M: upload files with bounded workers
        M-->>IX: uploaded
        IX->>V: upsert_batch(keys, vectors, captions, metadata)
        V-->>IX: ok
        IX->>JOB: update counters
    end
    IX->>JOB: mark completed or failed
    C->>API: GET /api/v1/index/{job_id}
    API->>JOB: get job snapshot
    API-->>C: IndexJobResponse(counters, status, error)
```

---

## 5) Health probe

`GET /health` — used by load balancers, Docker, and humans.

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as /health route
    participant E as EmbeddingService
    participant V as VectorStore
    participant M as ObjectStore

    C->>API: GET /health
    API->>E: is_loaded
    E-->>API: bool
    API->>V: get_collection_info()
    alt success
        V-->>API: dict(name, points_count, status)
    else failure
        V-->>API: raise
        API->>API: log warning, return error dict
    end
    API->>M: read .bucket attr (no remote call)
    M-->>API: bucket name
    API-->>C: HealthResponse(status="ok", model_loaded, qdrant, minio_bucket)
```

---

## 6) Migration from legacy artefacts

For users coming from a pre-computed `df.csv` + `df_image_embeds.npy`
checkpoint plus a local `images/` directory.

```mermaid
flowchart TD
    A[scripts/upload_images_to_minio.py] --> B[MigrationService.upload_images]
    B --> C[Iterate images/*.jpg]
    C --> D{object_exists in MinIO?}
    D -- yes --> E[Skip]
    D -- no --> F[ObjectStore.upload_file]
    F --> G[Bump uploaded counter]

    H[scripts/migrate_to_qdrant.py] --> I[MigrationService.migrate_embeddings_only]
    I --> J[Read df.csv TSV → image_path column]
    I --> K[Load df_image_embeds.npy]
    I --> L{"len(df) == len(embeds)?"}
    L -- no --> M[raise ValueError]
    L -- yes --> N[Read captions.json if present]
    N --> O[VectorStore.upsert_batch keys, embeds, captions]

    P[MigrationService.migrate_all] --> B
    P --> I
```

```mermaid
sequenceDiagram
    autonumber
    participant U as User
    participant Script as scripts/migrate_to_qdrant.py
    participant Mig as MigrationService
    participant FS as Filesystem
    participant V as VectorStore (Qdrant)

    U->>Script: uv run python scripts/migrate_to_qdrant.py
    Script->>Mig: migrate_embeddings_only()
    Mig->>FS: read df.csv (TSV) + df_image_embeds.npy + captions.json
    FS-->>Mig: DataFrame, np.ndarray, dict
    Mig->>Mig: validate lengths
    Mig->>V: upsert_batch(keys, embeds, captions)
    loop batches of 100
        V->>V: client.upsert(points, id=uuid5(NAMESPACE_URL, key))
    end
    V-->>Mig: ok
    Mig-->>Script: count
    Script-->>U: log "Migration finished: N embeddings upserted"
```

---

## 7) Gradio UI interactions

The UI is mounted at `/ui` and shares the *same* singleton services as the
REST API.

```mermaid
sequenceDiagram
    autonumber
    participant U as User (browser)
    participant G as Gradio UI
    participant S as SearchService
    participant I as ImageService

    U->>G: select "Text" mode, type query, set top_k, click Search
    G->>S: search_by_text(query, top_k)
    S-->>G: list[SearchResult]
    loop each result
        G->>I: get_image_url(image_path)
        I-->>G: presigned URL
    end
    G-->>U: render Gallery + cache results_state
    U->>G: click image in Gallery
    G->>G: on_select(evt.index, rows)
    G-->>U: show score + caption

    Note over U,G: Image mode swaps the input to gr.Image and calls search_by_image instead.
```

---

## 8) Storage shape

How a single fashion image lives across the two storage backends.

```mermaid
flowchart LR
    subgraph LocalFS["Local FS (only during indexing)"]
        IMG["dress_001.jpg"]
    end
    subgraph MinIO["MinIO bucket: fashion-images"]
        OBJ["object: images/dress_001.jpg"]
    end
    subgraph Qdrant["Qdrant collection: fashion_images"]
        POINT["point id = uuid5(NAMESPACE_URL,<br/>'images/dress_001.jpg')<br/>vector: 512-d<br/>payload: {image_path, caption, filename}"]
    end

    IMG -->|CLIP encode| VEC[(512-d vector)]
    IMG -->|ObjectStore.upload_file| OBJ
    VEC -->|VectorStore.upsert_batch| POINT
    POINT -.->|payload.image_path| OBJ
    OBJ -->|presigned URL| Client[(Client browser)]
```

Notes:

- `image_path` is the Qdrant payload field that ties a vector hit back to its
  MinIO object key.
- Because the point id is derived from `uuid5(NAMESPACE_URL, image_path)`,
  re-indexing the same image is idempotent — the existing point is overwritten
  rather than duplicated.
