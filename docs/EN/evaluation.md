# Evaluation And Benchmarking

Evaluation is split into four questions:

1. Does the code behave correctly?
2. Does retrieval return relevant images?
3. Does search/indexing meet latency and throughput targets for the deployment
   environment?
4. Can operators inspect health, metrics, logs, and job status?

## Evaluation Dimensions

| Dimension | Question | Tooling |
|---|---|---|
| Functional correctness | Do API contracts, indexing counters, auth, and failure states work? | `pytest` |
| Retrieval quality | Do text queries return relevant images? | `scripts/evaluate_retrieval.py` |
| Search performance | How fast is text search under concurrency? | `scripts/benchmark_search.py` |
| Indexing performance | How long does ingestion take? | `scripts/benchmark_indexing.py` |
| Operability | Can the service be inspected while running? | `/health`, `/metrics`, logs, job API |

## Included Evaluation Dataset

The repository includes:

```text
evaluation/deepfashion_weak_labels.jsonl
```

This file is generated from the real local DeepFashion dataset shape:

- filenames under `DeepFashion/images`;
- category labels encoded in filenames such as `WOMEN-Dresses` or
  `MEN-Shirts_Polos`;
- caption availability from `DeepFashion/captions.json`.

It contains 30 caption-to-image text queries. Each query uses a real caption
from `DeepFashion/captions.json`, and the relevant image is the source image for
that caption.

This is a **weak-label** evaluation set. It is useful for repeatable baseline
checks, but it is not the same as a human-labeled benchmark. A result can be
visually relevant even if it is not listed in `relevant`, and a category match
does not guarantee perfect semantic relevance.

Use this included set as a smoke/regression baseline:

- good for detecting obvious regressions after code/config changes;
- not sufficient to claim final product retrieval quality;
- not sufficient for comparing different models unless the same indexed data,
  query file, and search settings are used.

For a real release gate, create a human-reviewed query set where each query has
multiple acceptable relevant images. Fashion search often has many visually
valid matches, so a single source image per caption undercounts relevance.

The first recorded run is stored at:

```text
evaluation/reports/deepfashion_baseline_2026-05-16.md
```

## Query Set Format

Each JSONL line is one query case:

```jsonl
{"id":"df_caption_01","query":"The shirt this woman wears has short sleeves...","relevant":["images/WOMEN-Dresses-id_00000002-02_1_front.jpg"]}
```

Fields:

| Field | Meaning |
|---|---|
| `id` | Stable query id for reports. |
| `query` | Text sent to `/api/v1/search/text`. |
| `relevant` | Expected relevant `image_path` values returned by the API. |

`relevant` values must match returned `image_path` exactly.

## Retrieval Metrics

### Recall@K

Recall@K asks how many relevant images were found in the first K results.

If a query has 10 relevant images and top 10 contains 6 of them:

```text
Recall@10 = 6 / 10 = 0.60
```

For retrieval systems, Recall@K is usually the first quality metric to inspect.

### Precision@K

Precision@K asks how many of the first K returned images are listed as relevant.

If top 10 contains 6 relevant images:

```text
Precision@10 = 6 / 10 = 0.60
```

With weak labels, precision can look artificially low because visually similar
items outside the relevant list are counted as incorrect.

### mAP@K

Mean Average Precision rewards relevant images appearing earlier in the result
list. A system that returns relevant images at ranks 1, 2, and 3 scores better
than one that returns them at ranks 8, 9, and 10.

### nDCG@K

Normalized Discounted Cumulative Gain is another ranking quality metric.
Relevant images near the top contribute more than relevant images near rank K.

## Run Retrieval Evaluation

Before running evaluation, the image set must be indexed into Qdrant and MinIO.

ANN mode:

```bash
uv run python scripts/evaluate_retrieval.py \
  --base-url http://localhost:8000 \
  --queries evaluation/deepfashion_weak_labels.jsonl \
  --top-k 10 \
  --search-mode ann \
  --api-key "$API_KEY"
```

Exact baseline:

```bash
uv run python scripts/evaluate_retrieval.py \
  --base-url http://localhost:8000 \
  --queries evaluation/deepfashion_weak_labels.jsonl \
  --top-k 10 \
  --search-mode exact \
  --api-key "$API_KEY"
```

If API key auth is disabled, omit `--api-key`.

Optional HNSW query parameter:

```bash
uv run python scripts/evaluate_retrieval.py \
  --base-url http://localhost:8000 \
  --queries evaluation/deepfashion_weak_labels.jsonl \
  --top-k 10 \
  --search-mode ann \
  --hnsw-ef 256 \
  --api-key "$API_KEY"
```

Higher `hnsw_ef` can improve ANN recall but may increase latency.

## Suggested Acceptance Criteria

These are starter criteria for this repository. Adjust them for the actual
hardware, dataset size, and product expectations.

### Functional

Required:

```bash
uv run pytest tests/ -v
uv run ruff check src/ tests/ scripts/
uv run mypy src tests
```

All commands should pass before trusting retrieval or benchmark results.

### Retrieval Quality

Use exact search as the reference baseline:

- `exact` tells you how well the model/data/query set behave without ANN
  approximation loss.
- `ann` tells you how production search behaves with the configured Qdrant
  search parameters.

Starter thresholds for future runs of this weak-label set:

| Check | Suggested target |
|---|---:|
| Exact `recall_at_k` | `>= 0.50` after improving labels, or track against the current baseline |
| ANN `recall_at_k` | within `0.10` absolute of exact recall |
| ANN `ndcg_at_k` | within `0.10` absolute of exact nDCG |
| API errors during evaluation | `0` |

The first recorded weak-label baseline did not meet the starter recall target.
Use that result as a baseline, not as a final quality gate. Before treating
these thresholds as release requirements, improve the query set with multiple
human-approved relevant images per query.

Because the first baseline had identical ANN and exact metrics, that run did
not indicate a Qdrant ANN problem. It indicated a model/data/evaluation-label
limitation: exact search could not find the single weak-label target for many
queries either.

If exact recall is low, inspect:

- whether the query set labels are too narrow;
- whether the indexed dataset matches the query set;
- whether image paths in `relevant` match returned `image_path`;
- whether the CLIP model is appropriate for the category/query wording.

If exact is acceptable but ANN is much worse, inspect:

- `QDRANT_HNSW_EF`;
- Qdrant index build state;
- `SEARCH_MODE_DEFAULT`;
- whether `ann_indexed_only` is excluding non-indexed vectors.

### Performance

Performance targets must be recorded with hardware and config. A CPU laptop,
CPU Docker container, and GPU server have different expected latencies.

Starter targets for a small single-machine deployment:

| Check | Suggested target |
|---|---:|
| Search benchmark errors | `0` |
| Search p95 latency after model warm-up | owner-defined, record hardware |
| Indexing `failed_count` on clean dataset | `0` |
| Second unchanged indexing run | mostly `skipped_count` |

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

The report includes request count, errors, throughput, p50/p95/p99 latency, and
mean latency.

Run one warm-up search before benchmarking so the model is already loaded.

## Indexing Benchmark

```bash
uv run python scripts/benchmark_indexing.py \
  --base-url http://localhost:8000 \
  --images-dir /data/images \
  --api-key "$API_KEY"
```

The benchmark starts an indexing job, polls until completion/failure, and
reports counters, duration, and images per minute.

If `INDEXING_JOB_BACKEND=redis`, the API enqueues work and the separate
`clip-index-worker` process performs ingestion. If `INDEXING_JOB_BACKEND=memory`,
the API process runs the background job in its local executor. Record which mode
you used in benchmark reports because their failure modes and restart behavior
are different.

Counter interpretation:

- high `skipped_count`: unchanged files are skipped correctly;
- high `indexed_count`: many new files were inserted;
- high `updated_count`: many existing files changed;
- high `uploaded_only_count`: MinIO repair happened without CLIP re-encoding;
- high `failed_count`: inspect worker logs and input data.

## Baseline Report Template

Use:

```text
evaluation/reports/deepfashion_baseline_template.md
```

Fill it only with real command outputs. Do not invent metric values when the
service was not running or the dataset was not indexed.

Required context for every report:

- date;
- git commit;
- query set path;
- indexed image count;
- hardware;
- base URL;
- search config;
- ANN and exact retrieval metrics;
- benchmark results;
- pass/fail notes.
