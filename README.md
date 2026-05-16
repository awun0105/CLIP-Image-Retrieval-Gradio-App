<a id="readme-top"></a>

# CLIP Fashion-Products Image Retrieval Engine

A CLIP-based image retrieval service for fashion product catalogs. It supports
text-to-image and image-to-image search, stores vectors in Qdrant, stores image
objects in MinIO, and runs indexing as background jobs through Redis/RQ in the
production stack.

The repository provides the retrieval service layer: API, UI, indexing worker,
storage adapters, metrics, deployment configuration, and evaluation tooling. It
does not include unrelated product-platform features such as user accounts,
billing, inventory management, or multi-tenant authorization.

## Links

[![Hugging Face Space](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Space-yellow)](https://huggingface.co/spaces/anhquanlam/CLIP-Fashion-Product-Search)
[![Model on HF](https://img.shields.io/badge/%F0%9F%A4%97%20Model-DeepFashion_CLIP-orange)](https://huggingface.co/anhquanlam/clip-finetuned-deepfashion)
[![Dataset on HF](https://img.shields.io/badge/%F0%9F%A4%97%20Dataset-DeepFashion_Multimodal-green)](https://huggingface.co/datasets/anhquanlam/clip-deepfashion-multimodal)
[![YouTube Demo](https://img.shields.io/badge/YouTube-Project_Demo-red?logo=youtube)](https://www.youtube.com/watch?v=6h3SuES8a-M)

## Screenshots

<p align="center">
  <img src="https://github.com/user-attachments/assets/7c80a45c-7b72-4a3b-9c5f-20226c6cc32c" alt="Starting App" width="800">
  <br>
  <em>Starting App</em>
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/0106ffa4-4f47-4b47-a1d0-97faa58428b3" alt="Plaid Skirt Search" width="800">
  <br>
  <em>Text Search: "Plaid Skirt" results</em>
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/35eb958f-4707-4010-8d76-26f0668e5a92" alt="Image Upload" width="800">
  <br>
  <em>Image Upload Workflow</em>
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/b2bc5f5a-b289-4275-ae28-2e26b2d021f7" alt="Visual Search Results" width="800">
  <br>
  <em>Visual Similarity Search Results</em>
</p>

## What It Does

- **Text search**: type a natural-language query such as `red dress` or
  `black leather jacket`, embed it with CLIP, and retrieve visually relevant
  fashion images.
- **Image search**: upload a reference image, embed it with CLIP, and retrieve
  visually similar catalog items.
- **Incremental indexing**: scan local image folders and only encode/upload
  new or changed files by checking file metadata and SHA256 content hashes.
  Indexing retrieves only the Qdrant payload fields needed for state checks and
  writes vectors in configurable Qdrant upsert batches.
- **Background ingestion**: submit indexing jobs through the API or CLI; in the
  production stack Redis/RQ runs the long work outside the API request path.
- **Runtime operations**: API key auth, upload guardrails, Prometheus
  metrics, structured logs, Docker production compose, CI, backup/restore docs,
  and evaluation/benchmark tools.

## Architecture At A Glance

```mermaid
flowchart LR
    Client["Browser / API Client"] --> API["FastAPI + Gradio"]
    API --> Search["SearchService"]
    API --> Jobs["IndexingJobBackend"]
    Search --> Embed["EmbeddingService<br/>CLIP"]
    Search --> Qdrant[("Qdrant<br/>vectors")]
    Search --> MinIO[("MinIO<br/>images")]
    Jobs --> Redis[("Redis / RQ")]
    Redis --> Worker["Indexing Worker"]
    Worker --> Embed
    Worker --> MinIO
    Worker --> Qdrant
    API --> Metrics["/metrics<br/>Prometheus"]
```

The service separates responsibilities:

- FastAPI exposes API routes and mounts the Gradio UI.
- CLIP converts text/images into vectors.
- Qdrant performs cosine similarity search over vectors.
- MinIO stores image objects and returns presigned URLs.
- Redis/RQ decouples long indexing jobs from HTTP requests.
- Prometheus reads `/metrics` for operational visibility.

For full details, start with the documentation map:

[docs/README.md](docs/README.md)

## Repository Structure

```text
.
├── src/
│   ├── api/              # FastAPI app, routes, security, schemas, DI
│   ├── core/             # Embedding, search, indexing, jobs, metrics, logging
│   ├── db/               # Qdrant, MinIO, migration wrappers
│   ├── ui/               # Gradio UI mounted at /ui
│   ├── server.py         # clip-retrieval entrypoint
│   ├── worker.py         # clip-index-worker RQ worker
│   └── index_enqueue.py  # clip-index-enqueue CLI
├── scripts/              # Migration, evaluation, benchmark utilities
├── evaluation/           # Weak-label query set and report templates
├── tests/                # Unit/API tests with fakes and in-memory Qdrant
├── docs/
│   ├── README.md         # Documentation map
│   ├── EN/               # English documentation
│   ├── VN/               # Vietnamese docs placeholder for a later pass
│   └── plans/            # Planning notes, not user-facing docs
├── ops/prometheus/       # Prometheus scrape config
├── docker-compose.yml    # Local/simple compose stack
├── docker-compose.prod.yml
├── Dockerfile
├── Makefile
└── pyproject.toml
```

## Local Development Quickstart

Use this when you are coding/debugging on your laptop.

```bash
make dev
cp .env.example .env
docker compose up -d qdrant minio
make run
```

Open:

- UI: <http://localhost:8000/ui>
- API docs: <http://localhost:8000/docs>
- Health: <http://localhost:8000/health>
- Metrics: <http://localhost:8000/metrics>
- MinIO Console: <http://localhost:9001> (`minioadmin` / `minioadmin` by default)

Local development usually uses `.env`, `localhost` service endpoints, and API
key auth disabled for convenience.

Detailed guide: [docs/EN/local-development.md](docs/EN/local-development.md)

## Production Stack Quickstart

Use this when you want to run the service like a VPS deployment. Running the
production stack locally is a close Docker Compose simulation of how it would
run on a single VPS.

```bash
cp .env.production.example .env.production
# Edit .env.production: API_KEY, MinIO credentials, paths.
make prod-config
make prod-build
make prod-up
make prod-logs
```

Production compose starts:

- `app`: FastAPI + Gradio
- `worker`: RQ indexing worker
- `redis`: queue and job metadata
- `qdrant`: vector database
- `minio`: object storage
- `prometheus`: metrics scraper

Detailed guide: [docs/EN/deployment/production.md](docs/EN/deployment/production.md)

## API Examples

Text search:

```bash
curl -X POST http://localhost:8000/api/v1/search/text \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"query": "red dress", "top_k": 5, "search_mode": "ann"}'
```

Start indexing:

```bash
curl -X POST http://localhost:8000/api/v1/index/ \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"images_dir": "/data/images"}'
```

Poll an indexing job:

```bash
curl -H "X-API-Key: $API_KEY" \
  http://localhost:8000/api/v1/index/<job_id>
```

API guide: [docs/EN/api.md](docs/EN/api.md)

## Evaluation And Benchmarking

Evaluate retrieval quality with the included DeepFashion weak-label query set:

```bash
uv run python scripts/evaluate_retrieval.py \
  --base-url http://localhost:8000 \
  --queries evaluation/deepfashion_weak_labels.jsonl \
  --top-k 10 \
  --search-mode ann \
  --api-key "$API_KEY"
```

Benchmark search latency:

```bash
uv run python scripts/benchmark_search.py \
  --base-url http://localhost:8000 \
  --query "red dress" \
  --requests 100 \
  --concurrency 10 \
  --api-key "$API_KEY"
```

Evaluation guide: [docs/EN/evaluation.md](docs/EN/evaluation.md)

The included query set is derived from the DeepFashion dataset filenames and is
intended as a repeatable weak-label baseline, not a human-labeled gold
benchmark.

## Development Checks

```bash
uv run pytest tests/ -v
uv run ruff check src/ tests/ scripts/
uv run mypy src tests
docker build -t clip-image-retrieval:v3-smoke .
```

## Documentation

Start here:

[docs/README.md](docs/README.md)

The English documentation under `docs/EN/` is the current authoritative
documentation set. The Vietnamese documentation folder is reserved for a later
translation pass.

## License

Distributed under the MIT License. See [LICENSE](LICENSE).

<p align="right">(<a href="#readme-top">back to top</a>)</p>
