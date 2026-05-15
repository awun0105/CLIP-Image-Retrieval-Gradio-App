# V3 Production Readiness Plan

## Summary

V3 đưa project từ production-ready core MVP lên minimum full-production-grade
MVP cho visual search service kiểu Pinterest/e-commerce.

Technical direction:

- Deployment baseline: Docker Compose production cho VPS/single-node, có đường
  nâng cấp sang Kubernetes sau này.
- Queue: Redis + RQ.
- Observability: Prometheus metrics + JSON structured logs.
- Security: API key auth + configurable upload guardrails.
- Evaluation: retrieval quality evaluation + performance benchmark scripts.
- Ingestion automation: CLI enqueue job + cron/systemd guide.

## Workflow Rules During Implementation

- Làm việc trên branch `v3-production-readiness`.
- Không implement trên `master`.
- Commit sau mỗi phần nhỏ đã hoàn thành và test được.
- Commit style: Conventional Commit, ví dụ:
  - `ci: add production validation workflow`
  - `feat(indexing): move jobs to redis rq`
  - `feat(api): add api key auth`
  - `feat(observability): add prometheus metrics`
  - `docs(deploy): add production runbook`
- Không commit secret, `.env`, dataset, model cache, Qdrant/MinIO volumes.
- Nếu có bước cần manual setting mà agent không tự làm được, hướng dẫn rõ:
  - cần tạo secret gì;
  - đặt ở đâu;
  - command nào cần chạy;
  - cách verify.
- Sau khi implement xong, cung cấp hướng dẫn chạy:
  - local dev;
  - production compose;
  - worker;
  - indexing;
  - search;
  - metrics;
  - evaluation/benchmark.

## Key Implementation Changes

### 1. Branch + Plan Artifact

- Tạo branch `v3-production-readiness`.
- Tạo file plan này làm source of truth cho v3.
- Vì sao: branch riêng giúp review/rollback rõ; plan file giữ quyết định kỹ
  thuật tập trung.
- Tradeoff: scope branch lớn hơn bugfix nhỏ, nhưng hợp lý vì v3 chạm CI,
  deployment, security, queue, observability và evaluation.

### 2. CI/CD Pipeline

- Thêm GitHub Actions chạy:
  - `ruff check`;
  - `mypy`;
  - `pytest`;
  - Docker build smoke test;
  - optional GHCR push khi merge/tag.
- Vì sao: production-grade tối thiểu cần validation tự động.
- Tradeoff: CI chậm hơn local, nhưng giảm regression.
- Maintainability: reuse `uv`/Makefile commands, không duplicate logic build/test
  rải rác.
- Manual setting nếu bật GHCR push:
  - kiểm tra GitHub Actions permission `Read and write permissions`;
  - nếu dùng registry khác, cần tạo secret token.

### 3. Production Docker Compose

- Thêm:
  - `docker-compose.prod.yml`;
  - `.env.production.example`;
  - Makefile targets prod nếu phù hợp.
- Prod stack:
  - `app`;
  - `worker`;
  - `redis`;
  - `qdrant`;
  - `minio`;
  - `prometheus`.
- Thêm healthchecks, restart policies, named volumes, env-based secrets.
- Vì sao: app và indexing worker cần tách process; Redis/Prometheus cần có trong
  stack production MVP.
- Tradeoff: Compose chưa autoscale mạnh như Kubernetes, nhưng phù hợp minimum
  production MVP.
- Manual setting:
  - copy `.env.production.example` thành `.env.production`;
  - đổi MinIO credentials, API key, secret values.

### 4. API Key Auth + Configurable Upload Guardrails

- Thêm config:
  - `ENABLE_API_KEY_AUTH`;
  - `API_KEY`;
  - `MAX_UPLOAD_BYTES`;
  - `MAX_IMAGE_PIXELS`;
  - `ALLOWED_IMAGE_CONTENT_TYPES`.
- REST `/api/v1/*` yêu cầu `X-API-Key` khi auth bật.
- `/health` public.
- `/metrics` chỉ expose nội bộ trong prod compose hoặc được bảo vệ theo config.
- Image upload:
  - đọc bounded stream theo config;
  - `MAX_UPLOAD_BYTES=0` nghĩa là unlimited;
  - default permissive để không làm giảm chất lượng ảnh;
  - `MAX_IMAGE_PIXELS` chống decompression bomb.
- Vì sao: bảo vệ API khỏi abuse/OOM nhưng vẫn cho phép ảnh chất lượng cao.
- Tradeoff: API key đơn giản hơn OAuth, phù hợp service-level integration MVP.

### 5. Redis/RQ Durable Indexing Jobs

- Thêm dependency Redis/RQ.
- Tách job backend khỏi `IndexingService`:
  - API enqueue job;
  - worker execute job;
  - status đọc từ Redis metadata.
- Giữ API contract:
  - `POST /api/v1/index/` trả `job_id`;
  - `GET /api/v1/index/{job_id}` trả status/counters/error/timestamps.
- Thêm worker entrypoint, ví dụ project script `clip-index-worker`.
- Vì sao: in-memory jobs không durable và không scale nhiều app instances.
- Tradeoff: thêm Redis/worker vận hành, nhưng giảm coupling giữa API và indexing
  execution.

### 6. Prometheus Metrics + Structured Logs

- Thêm `/metrics` bằng `prometheus-client`.
- Thêm middleware request metrics + request id.
- Thêm metrics cho:
  - API latency/count;
  - search latency;
  - embedding latency;
  - Qdrant latency;
  - indexing counters;
  - worker job status;
  - queue wait time.
- Thêm `LOG_FORMAT=text|json`.
- JSON logs trong production.
- Vì sao: production cần quan sát latency, lỗi, queue và throughput.
- Tradeoff: metrics/logging có overhead nhỏ; giữ label bounded để tránh
  Prometheus cardinality bottleneck.

### 7. Evaluation & Benchmarking Toolkit

- Thêm:
  - `docs/evaluation.md`;
  - `scripts/evaluate_retrieval.py`;
  - `scripts/benchmark_search.py`;
  - `scripts/benchmark_indexing.py`.
- Retrieval metrics:
  - Recall@K;
  - Precision@K;
  - mAP@K;
  - nDCG@K;
  - ANN vs exact recall comparison.
- Benchmark metrics:
  - p50/p95/p99 latency;
  - throughput;
  - error rate;
  - images/minute;
  - indexed/skipped/failed count.
- Vì sao: hiện repo có correctness tests nhưng chưa có quality/performance
  evaluation.
- Tradeoff: benchmark nặng không chạy mặc định trong CI; chỉ có smoke fixture
  nhỏ.

### 8. Automated Ingestion CLI / Scheduled Operation

- Thêm CLI, ví dụ `clip-index-enqueue`.
- CLI enqueue indexing job qua Redis/RQ hoặc API-compatible service layer.
- Docs hướng dẫn cron/systemd timer.
- Vì sao: production ingestion không nên phụ thuộc Swagger/curl thủ công.
- Tradeoff: chưa build scheduler UI; CLI + cron/systemd đủ cho MVP.

### 9. Backup / Restore Docs

- Thêm `docs/deployment/backup-restore.md`.
- Nội dung:
  - Qdrant snapshot/volume backup;
  - MinIO bucket backup/restore;
  - Redis job state note;
  - secret/env backup checklist;
  - restore validation checklist.
- Vì sao: production tối thiểu cần rollback dữ liệu và khôi phục storage.
- Tradeoff: v3 làm runbook trước, chưa làm backup operator.

### 10. Production Deployment Docs + Release Checklist

- Thêm `docs/deployment/production.md`.
- Nội dung:
  - first deploy;
  - env setup;
  - compose prod commands;
  - worker commands;
  - health checks;
  - metrics checks;
  - queue checks;
  - rollback;
  - troubleshooting.
- Thêm release checklist.
- Vì sao: production-grade cần quy trình vận hành, không chỉ code.

## Evaluation Strategy

- Automated in CI:
  - lint/type/test;
  - Docker build;
  - small evaluation smoke test.
- Manual/release-triggered:
  - full retrieval evaluation;
  - search benchmark;
  - indexing benchmark;
  - ANN vs exact comparison;
  - backup/restore dry run.
- Manual acceptance:
  - start prod stack;
  - check `/health`;
  - check `/metrics`;
  - enqueue indexing;
  - poll status;
  - run text/image search;
  - inspect logs;
  - restart app and verify Redis-backed job status remains.

## Test Plan

- API auth:
  - missing key;
  - invalid key;
  - valid key;
  - auth disabled.
- Upload guardrails:
  - unlimited mode;
  - size limit mode;
  - invalid content type;
  - pixel/decompression protection.
- RQ job flow:
  - enqueue;
  - worker execution;
  - status mapping;
  - failure state;
  - app restart with Redis preserved.
- Observability:
  - `/metrics` exposes expected metrics;
  - metric labels are bounded;
  - request id appears in logs.
- Evaluation:
  - metrics calculations correct on deterministic fixture;
  - benchmark scripts run against local app.
- Validation commands:
  - `uv run ruff check src/ tests/ scripts/`
  - `uv run mypy src tests`
  - `uv run pytest tests/ -v`
  - `docker compose -f docker-compose.prod.yml config`
  - Docker image build.

## Assumptions / Defaults

- Branch: `v3-production-readiness`.
- Queue: Redis + RQ.
- Deployment: Docker Compose production.
- Auth: API key, not OAuth/OIDC.
- Upload guardrails: configurable and permissive by default.
- `MAX_UPLOAD_BYTES=0` means unlimited.
- Gradio UI remains demo/admin UI; production public access should be protected
  or disabled.
- Manual steps will be documented only when they require real external
  settings/secrets.
- Out of v3: Kubernetes/Helm, OAuth/OIDC, Triton/TorchServe, multi-tenant RBAC,
  full scheduler UI.
