# Evaluation Guide

This project should be evaluated across four dimensions:

1. **Functional correctness**: API contracts, indexing counters, search
   responses, and failure states behave as expected. This is covered by pytest.
2. **Retrieval quality**: text queries return relevant images and ANN search
   stays close to exact search.
3. **Performance**: search latency, throughput, and indexing throughput stay
   within the target budget for the deployment environment.
4. **Operability**: health, metrics, logs, job status, and recovery runbooks are
   sufficient to operate the service.

## Retrieval Quality

Create a JSONL query set:

```jsonl
{"id": "q1", "query": "red dress", "relevant": ["images/red_dress.jpg"]}
{"id": "q2", "query": "black leather jacket", "relevant": ["images/jacket_1.jpg", "images/jacket_2.jpg"]}
```

Run evaluation:

```bash
uv run python scripts/evaluate_retrieval.py \
  --base-url http://localhost:8000 \
  --queries eval_queries.jsonl \
  --top-k 10 \
  --search-mode ann
```

Run exact baseline:

```bash
uv run python scripts/evaluate_retrieval.py \
  --base-url http://localhost:8000 \
  --queries eval_queries.jsonl \
  --top-k 10 \
  --search-mode exact
```

Compare ANN vs exact to estimate ANN recall loss.

Metrics reported:

- `recall_at_k`
- `precision_at_k`
- `map_at_k`
- `ndcg_at_k`

## Search Benchmark

```bash
uv run python scripts/benchmark_search.py \
  --base-url http://localhost:8000 \
  --query "red dress" \
  --top-k 10 \
  --requests 100 \
  --concurrency 10
```

The benchmark reports throughput and p50/p95/p99 latency.

## Indexing Benchmark

```bash
uv run python scripts/benchmark_indexing.py \
  --base-url http://localhost:8000 \
  --images-dir /path/to/images
```

The benchmark reports job counters, duration, and images/minute.

## Automation Policy

- CI should run correctness tests and lightweight evaluation fixtures only.
- Full retrieval evaluation and benchmarks should run before releases or after
  infrastructure changes.
- Manual acceptance should verify UI search, API search, indexing status,
  `/health`, `/metrics`, and logs.
