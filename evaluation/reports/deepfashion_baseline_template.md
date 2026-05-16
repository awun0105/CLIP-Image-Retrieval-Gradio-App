# DeepFashion Weak-Label Baseline Report

## Run Context

| Field | Value |
|---|---|
| Date | |
| Git commit | |
| Query set | `evaluation/deepfashion_weak_labels.jsonl` |
| Query count | 30 |
| Indexed image count | |
| Hardware | |
| API base URL | |
| Search config | |

## Retrieval Quality

| Mode | top_k | recall_at_k | precision_at_k | map_at_k | ndcg_at_k | Notes |
|---|---:|---:|---:|---:|---:|---|
| ann | 10 | | | | | |
| exact | 10 | | | | | |

## Performance

| Benchmark | Requests / Images | Concurrency | p50 ms | p95 ms | p99 ms | Throughput | Errors |
|---|---:|---:|---:|---:|---:|---:|---:|
| search | | | | | | | |
| indexing | | | | | | | |

## Decision

| Check | Pass/Fail | Notes |
|---|---|---|
| Functional tests pass | | |
| ANN quality close to exact baseline | | |
| Search latency within target for environment | | |
| Indexing failed_count acceptable | | |
| Metrics/logs available | | |

## Notes

This query set uses weak labels derived from DeepFashion filenames/categories.
It is useful for a repeatable baseline, but it is not a substitute for a
human-labeled retrieval benchmark.
