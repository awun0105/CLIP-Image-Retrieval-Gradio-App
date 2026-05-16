# Repository Guidelines

## Project Structure & Module Organization

This Python 3.10+ CLIP fashion-product image retrieval service keeps main code in
`src/`:

- `src/api/`: FastAPI app factory, dependency singletons, API key security, request
  middleware, routes, metrics endpoint, and API schemas.
- `src/core/`: CLIP embedding, foreground/background inference gating, search,
  incremental indexing, indexing job state, image handling, metrics, logging, and
  shared schemas.
- `src/db/`: Qdrant vector store, MinIO object store, and legacy migration service.
- `src/ui/`: Gradio Blocks interface mounted at `/ui`.
- `src/config.py`: Pydantic settings for local, production, security, indexing, Redis,
  Qdrant, MinIO, observability, and upload limits.
- `src/server.py`, `src/worker.py`, and `src/index_enqueue.py`: API/UI entrypoint,
  RQ indexing worker entrypoint, and scheduled/manual indexing enqueue CLI.

Tests are in `tests/`, operational/evaluation utilities are in `scripts/`, retrieval
evaluation assets are in `evaluation/`, and Prometheus config is in `ops/prometheus/`.
Legacy Hugging Face source is under `Source-huggingface/`; avoid changing it unless
the task targets the legacy app.

Current user-facing docs are organized under `docs/EN/`. `docs/VN/` is a placeholder
for a later Vietnamese documentation pass. `docs/README.md` is the documentation
navigation file. Do not treat `docs/plans/` as current user-facing documentation.

## Build, Test, and Development Commands

Use `uv` through the `Makefile` when possible:

- `make dev`: install runtime and dev dependencies into `.venv`.
- `make run`: start FastAPI and Gradio via `uv run clip-retrieval`.
- `make test`: run `uv run pytest tests/ -v`.
- `make lint`: run Ruff checks for `src/` and `tests/`.
- `make format`: format Python files with Ruff.
- `make docker-up`: start the full Docker stack: app, Qdrant, and MinIO.
- `make docker-down`: stop the Docker stack.
- `make prod-config`: validate the production Compose stack using `.env.production`.
- `make prod-build`: build the production Compose images.
- `make prod-up`: start the production stack: app, worker, Redis, Qdrant, MinIO, and Prometheus.
- `make prod-down`: stop the production stack.
- `make prod-logs`: follow app and worker logs.
- `make migrate`: run `scripts/migrate_to_qdrant.py`.

Useful direct commands:

- `uv run clip-index-worker`: start the RQ indexing worker when
  `INDEXING_JOB_BACKEND=redis`.
- `uv run clip-index-enqueue --images-dir <path>`: enqueue an indexing job from CLI.
- `uv run python scripts/evaluate_retrieval.py --base-url http://localhost:8000 --queries evaluation/deepfashion_weak_labels.jsonl --top-k 10 --search-mode ann`:
  run the real retrieval evaluation sample.
- `uv run python scripts/benchmark_search.py --base-url http://localhost:8000` and
  `uv run python scripts/benchmark_indexing.py --base-url http://localhost:8000 --images-dir <path>`:
  run lightweight performance checks.

For local development without external Qdrant persistence, set `QDRANT_MODE=memory`
in `.env`. For a production-like local stack, use `.env.production` with
`INDEXING_JOB_BACKEND=redis` and run `make prod-up`.

## Coding Style & Naming Conventions

Ruff is the formatter and linter. Keep Python line length near 100 characters and follow the configured lint set: `E`, `F`, `I`, `W`, and `B`. Use 4-space indentation, type hints for public functions, and modules aligned with existing service boundaries. Prefer descriptive snake_case for functions, variables, fixtures, and modules; use PascalCase for classes and Pydantic schemas.

## Testing Guidelines

Tests use `pytest` with `pytest-asyncio` and `pythonpath = ["src"]`. Put tests in
`tests/test_*.py`, and use fixtures from `tests/conftest.py` for isolated settings,
in-memory Qdrant, mocked MinIO, Redis/RQ test behavior, and deterministic fake
embeddings. Run `make test` before submitting. For V3 production-readiness changes,
also run `uv run ruff check src/ tests/ scripts/` and `uv run mypy src tests`.
Add tests when changing API routes, retrieval behavior, storage adapters, indexing
job queue behavior, security/configuration defaults, metrics/logging, or evaluation
utilities.

Docs-only changes should still be checked for stale commands and broken links. Do not update docs by copying old planning notes without verifying them against source code.

Evaluation reports must be based on real script output. Do not invent retrieval
metrics. If a baseline changes, update both `evaluation/reports/` and
`docs/EN/evaluation.md` with the command, dataset/query file, search mode, and
interpretation.

## Commit & Pull Request Guidelines

Recent history uses concise Conventional Commit-style subjects, for example `fix(core): extract pooler_output from CLIP feature returns`. Use `type(scope): summary` for non-merge commits when practical. Pull requests should include a short description, test results, linked issues, and screenshots or API examples for UI/API-visible changes.

## Security & Configuration Tips

Configuration is loaded from environment variables and optional dotenv files. `.env`
is for local development. `.env.production` is for a production-like Compose stack
and must remain local. Do not commit secrets, production MinIO credentials, Qdrant
API keys, Redis credentials, large model files, generated datasets, local vector-store
data, MinIO/Qdrant/Redis volumes, `.env`, or `.env.production`.

`docs/QA.md` and `docs/plans/*` are intentionally ignored/local. Do not force-add them unless the user explicitly asks.

Keep these operational constraints in mind:

- API key auth is controlled by `ENABLE_API_KEY_AUTH`, `API_KEY`, and the `X-API-Key`
  header.
- Upload guardrails are controlled by `MAX_UPLOAD_BYTES`, `MAX_IMAGE_PIXELS`, and
  `ALLOWED_IMAGE_CONTENT_TYPES`.
- Indexing jobs support an in-memory backend for local/MVP runs and a Redis/RQ backend
  for production-like durability and worker isolation.
- Qdrant supports `memory`, `local`, and `remote` modes. Keep query-time search params
  separate from collection build-time indexing thresholds.
- `/metrics` is available only when `ENABLE_METRICS=true`; production Compose includes
  Prometheus.

When changing APIs, configuration, deployment behavior, indexing flow, evaluation
scripts, production operations, or observability, update the relevant files under
`docs/EN/` and the root `README.md` in the same change. Keep technical docs practical:
explain how the system works and how to operate it; avoid portfolio-style self-review
or AI-report language in user-facing docs.
