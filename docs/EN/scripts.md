# Maintenance Scripts

This page documents helper scripts under `scripts/`. They are not separate
services. Each script uses the same `Settings` object as the application, so the
active `.env` or environment variables decide which Qdrant, MinIO, Redis, and
data paths are used.

Run scripts from the repository root with `uv run python ...`.

Important environment behavior:

- the application automatically reads `.env`;
- production compose injects `.env.production` through Docker Compose;
- a standalone `uv run ...` command does not automatically read
  `.env.production` unless you export those values first.

For one-off production-style commands on a host, use:

```bash
set -a
source .env.production
set +a
uv run python scripts/<script_name>.py
```

`set -a` matters because sourced `KEY=value` entries are shell variables by
default. Child processes such as `uv run` only receive exported environment
variables.

## Migration And Storage Utilities

### `scripts/migrate_to_qdrant.py`

Migrates legacy DeepFashion embedding artifacts into Qdrant.

Use this when you already have the legacy `df.csv` and `.npy` embedding files
under `LEGACY_INDEX_PATH` and want to populate the current Qdrant collection
without re-encoding every image with CLIP.

```bash
uv run python scripts/migrate_to_qdrant.py
```

Relevant settings:

- `LEGACY_INDEX_PATH`: folder containing legacy `df.csv` and
  `df_image_embeds.npy`;
- `CAPTIONS_PATH`: optional captions JSON used to attach captions to payloads;
- `QDRANT_MODE`, `QDRANT_URL`, `QDRANT_COLLECTION`: target Qdrant settings.

Tradeoff: this path trusts existing embedding files. Use normal indexing when
you want embeddings generated from the configured `MODEL_ID`.

### `scripts/upload_images_to_minio.py`

Uploads legacy image files into MinIO without running vector indexing.

```bash
uv run python scripts/upload_images_to_minio.py
```

Use this only for maintenance or recovery flows where Qdrant vectors already
exist and MinIO objects need to be populated separately. Normal ingestion should
use the indexing job API or `clip-index-enqueue`, because those paths keep
Qdrant and MinIO reconciled together.

Relevant settings:

- `LEGACY_IMAGES_PATH`: local image directory;
- `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET`.

### `scripts/update_qdrant_index_config.py`

Applies configured Qdrant HNSW/optimizer thresholds to an existing collection.

```bash
uv run python scripts/update_qdrant_index_config.py
```

Use this after changing:

- `QDRANT_INDEXING_THRESHOLD`;
- `QDRANT_FULL_SCAN_THRESHOLD`.

This does not re-embed images. It only updates Qdrant collection configuration
where Qdrant supports runtime updates.

## Evaluation And Benchmarking Utilities

### `scripts/evaluate_retrieval.py`

Runs retrieval quality evaluation against the API using a JSONL query file.

```bash
uv run python scripts/evaluate_retrieval.py \
  --base-url http://localhost:8000 \
  --queries evaluation/deepfashion_weak_labels.jsonl \
  --top-k 10 \
  --search-mode ann
```

See [evaluation.md](evaluation.md) for metric definitions, the included
DeepFashion weak-label query set, and baseline interpretation.

### `scripts/benchmark_search.py`

Sends repeated text search requests to estimate API latency under configurable
request count and concurrency.

```bash
uv run python scripts/benchmark_search.py \
  --base-url http://localhost:8000 \
  --query "red dress" \
  --requests 100 \
  --concurrency 10
```

Use this for rough local performance checks, not as a replacement for a real
production load test.

### `scripts/benchmark_indexing.py`

Measures indexing job behavior through the API for a given image directory.

```bash
uv run python scripts/benchmark_indexing.py \
  --base-url http://localhost:8000 \
  --images-dir /data/images
```

This script is useful after changing indexing batch size, MinIO upload workers,
or Qdrant write settings.

## CLI Entrypoints Instead Of Scripts

The package also exposes two installed CLI commands:

```bash
uv run clip-index-worker
uv run clip-index-enqueue --images-dir /data/images
```

Use `clip-index-worker` for Redis/RQ production-like indexing workers. Use
`clip-index-enqueue` for manual or scheduled ingestion jobs when
`INDEXING_JOB_BACKEND=redis`.

When these commands run on the host, `REDIS_URL` must be reachable from the
host, for example `redis://localhost:6379/0`. When they run inside the
production compose network, `redis://redis:6379/0` is correct because `redis`
is the Docker service name.
