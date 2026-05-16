# Evaluation And Benchmarking

Evaluation answers two different questions:

1. **Does the system work correctly?**
2. **Does the retrieval quality and performance meet expectations?**

A production-oriented retrieval project needs both.

## Evaluation Dimensions

| Dimension | Question | Tooling |
|---|---|---|
| Functional correctness | Do API contracts, indexing counters, auth, and failure states work? | `pytest` |
| Retrieval quality | Do text queries return relevant images? | `scripts/evaluate_retrieval.py` |
| Search performance | How fast is text search under concurrency? | `scripts/benchmark_search.py` |
| Indexing performance | How long does ingestion take? | `scripts/benchmark_indexing.py` |
| Operability | Can we inspect health, logs, metrics, and job status? | `/health`, `/metrics`, logs |

## Manual vs Automated Evaluation

### Manual Evaluation

Manual evaluation means a human tries queries and visually inspects results.

Use it for:

- quick demo checks;
- UI acceptance;
- sanity-checking weird queries;
- verifying images load correctly.

Manual evaluation is easy, but subjective. It is not enough for release
confidence.

### Automated Evaluation

Automated evaluation uses a query set with known relevant images.

Use it for:

- comparing ANN vs exact search;
- checking if a model/indexing change made quality worse;
- generating repeatable metrics for portfolio or releases;
- regression testing retrieval behavior over time.

## Query Set Format

Create a JSONL file. Each line is one query case:

```jsonl
{"id": "q1", "query": "red dress", "relevant": ["images/red_dress_1.jpg", "images/red_dress_2.jpg"]}
{"id": "q2", "query": "black leather jacket", "relevant": ["images/jacket_1.jpg"]}
```

Fields:

| Field | Meaning |
|---|---|
| `id` | Stable query id for humans and reports. |
| `query` | Text query sent to `/api/v1/search/text`. |
| `relevant` | List of Qdrant/MinIO image paths that should be considered correct. |

Important: `relevant` values must match returned `image_path` values, usually
like `images/<filename>.jpg`.

## Retrieval Metrics

### Recall@K

Recall@K asks:

> Out of all correct images, how many did the system find in the top K?

Example: if there are 4 relevant images and top 10 contains 3 of them,
`Recall@10 = 3 / 4 = 0.75`.

This is usually the most important metric for image retrieval.

### Precision@K

Precision@K asks:

> Out of the top K returned images, how many are correct?

Example: if top 10 contains 3 correct images, `Precision@10 = 3 / 10 = 0.30`.

### mAP@K

Mean Average Precision rewards correct results appearing earlier in the ranking.
If two systems find the same relevant images but one puts them near the top,
that system receives a higher mAP.

### nDCG@K

Normalized Discounted Cumulative Gain also rewards ranking quality. Correct
items near rank 1 count more than correct items near rank K.

## Run Retrieval Evaluation

ANN mode:

```bash
uv run python scripts/evaluate_retrieval.py \
  --base-url http://localhost:8000 \
  --queries eval_queries.jsonl \
  --top-k 10 \
  --search-mode ann \
  --api-key "$API_KEY"
```

Exact baseline:

```bash
uv run python scripts/evaluate_retrieval.py \
  --base-url http://localhost:8000 \
  --queries eval_queries.jsonl \
  --top-k 10 \
  --search-mode exact \
  --api-key "$API_KEY"
```

Compare ANN vs exact. If exact performs much better, ANN/index settings may be
too aggressive or the index may not be fully built.

Optional HNSW query parameter:

```bash
uv run python scripts/evaluate_retrieval.py \
  --base-url http://localhost:8000 \
  --queries eval_queries.jsonl \
  --top-k 10 \
  --search-mode ann \
  --hnsw-ef 256 \
  --api-key "$API_KEY"
```

Higher `hnsw_ef` may improve recall but can increase latency.

## Search Benchmark

```bash
uv run python scripts/benchmark_search.py \
  --base-url http://localhost:8000 \
  --query "red dress" \
  --top-k 10 \
  --requests 100 \
  --concurrency 10 \
  --api-key "$API_KEY"
```

The report includes:

- total requests;
- errors;
- throughput in requests/second;
- p50/p95/p99 latency;
- mean latency.

Use this after changes to:

- model/device;
- Qdrant search settings;
- API route behavior;
- Docker resource limits;
- infrastructure.

## Indexing Benchmark

```bash
uv run python scripts/benchmark_indexing.py \
  --base-url http://localhost:8000 \
  --images-dir /data/images \
  --api-key "$API_KEY"
```

The benchmark:

1. Starts an indexing job.
2. Polls until completion or failure.
3. Reports counters, duration, and images/minute.

Interpret counters:

- high `skipped_count`: incremental indexing is working for unchanged data;
- high `indexed_count`: new catalog ingestion;
- high `updated_count`: many existing files changed;
- high `uploaded_only_count`: MinIO repair happened without CLIP re-encoding;
- high `failed_count`: inspect logs and input files.

## CI vs Release Evaluation

CI should run:

```bash
uv run pytest tests/ -v
uv run ruff check src/ tests/ scripts/
uv run mypy src tests
docker build -t clip-image-retrieval:v3-smoke .
```

Full retrieval evaluation should run:

- before releases;
- after model changes;
- after Qdrant search/index parameter changes;
- after indexing pipeline changes;
- after major infrastructure changes.

## What Exists And What Is Still Missing

Already implemented:

- unit/API tests;
- retrieval quality script;
- search benchmark;
- indexing benchmark;
- exact vs ANN comparison capability;
- metrics/logs for runtime observation.

Still useful for a stricter production release:

- a larger labeled evaluation dataset;
- versioned evaluation reports;
- minimum metric thresholds as release gates;
- dashboard for search/indexing latency over time;
- load tests that include image search, not only text search;
- GPU vs CPU benchmark comparison if deploying GPU inference.

For portfolio usage, a small curated query set plus benchmark results is enough
to demonstrate that the project is measurable and not only visually demoed.
