# DeepFashion Weak-Label Baseline Report - 2026-05-16

## Run Context

| Field | Value |
|---|---|
| Date | 2026-05-16 |
| Git commit | `b1c17a2` |
| Query set | `evaluation/deepfashion_weak_labels.jsonl` |
| Query count | 30 |
| Relevant labels | 1 image per query, derived from real DeepFashion captions/filenames |
| Indexed vectors | 44,098 |
| Qdrant collection | `fashion_images` |
| Hardware | 12 CPU threads, Linux x86_64 |
| API base URL | `http://127.0.0.1:8000` |
| Model state | loaded during evaluation |

## Retrieval Quality

Commands:

```bash
uv run python scripts/evaluate_retrieval.py \
  --base-url http://127.0.0.1:8000 \
  --queries evaluation/deepfashion_weak_labels.jsonl \
  --top-k 10 \
  --search-mode ann

uv run python scripts/evaluate_retrieval.py \
  --base-url http://127.0.0.1:8000 \
  --queries evaluation/deepfashion_weak_labels.jsonl \
  --top-k 10 \
  --search-mode exact
```

| Mode | top_k | queries | recall_at_k | precision_at_k | map_at_k | ndcg_at_k |
|---|---:|---:|---:|---:|---:|---:|
| ann | 10 | 30 | 0.3667 | 0.0367 | 0.1365 | 0.1892 |
| exact | 10 | 30 | 0.3667 | 0.0367 | 0.1365 | 0.1892 |

## Interpretation

ANN and exact produced the same metrics in this run, so the observed misses are
not caused by ANN approximation loss. They are caused by one or more of:

- the weak-label set only marks one exact image as relevant per caption;
- visually similar or semantically valid images are counted as incorrect if
  they are not the single listed `relevant` item;
- some captions describe multiple garments/accessories and may match nearby
  images better than the exact source filename;
- the evaluation set is small and intended as a repeatable smoke baseline, not
  a human-labeled ranking benchmark.

## Decision

| Check | Result | Notes |
|---|---|---|
| Evaluation command completed | Pass | ANN and exact completed with 30 queries. |
| API errors during evaluation | Pass | No HTTP errors were reported by the script. |
| ANN close to exact | Pass | Metrics are identical in this run. |
| Weak-label Recall@10 starter target `>= 0.50` | Not met | Current value is 0.3667. This does not prove retrieval is unusable; it shows the weak-label set is strict and should be improved with human labels before using it as a quality gate. |

## Follow-Up

Use this report as the first repeatable baseline. For a release gate, build a
human-labeled query set where each query has multiple acceptable relevant
images, then rerun ANN and exact evaluation.
