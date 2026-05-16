# Repository Guidelines

## Project Structure & Module Organization

This Python 3.10+ CLIP retrieval service keeps main code in `src/`:

- `src/api/`: FastAPI app factory, dependencies, routes, and API schemas.
- `src/core/`: embedding, search, indexing, image handling, and shared schemas.
- `src/db/`: Qdrant vector store, MinIO object store, and migration service.
- `src/ui/`: Gradio Blocks interface mounted at `/ui`.
- `src/config.py` and `src/server.py`: environment settings and app entry point.

Tests are in `tests/`, architecture notes in `docs/`, and one-off migration utilities in `scripts/`. Legacy Hugging Face source is under `Source-huggingface/`; avoid changing it unless the task targets the legacy app.

Current user-facing docs are organized under `docs/EN/`. `docs/VN/` is a placeholder for a later Vietnamese documentation pass. Do not treat `docs/plans/` as current user-facing documentation.

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

For local development without sidecars, set `QDRANT_MODE=memory` in `.env`.

## Coding Style & Naming Conventions

Ruff is the formatter and linter. Keep Python line length near 100 characters and follow the configured lint set: `E`, `F`, `I`, `W`, and `B`. Use 4-space indentation, type hints for public functions, and modules aligned with existing service boundaries. Prefer descriptive snake_case for functions, variables, fixtures, and modules; use PascalCase for classes and Pydantic schemas.

## Testing Guidelines

Tests use `pytest` with `pytest-asyncio` and `pythonpath = ["src"]`. Put tests in `tests/test_*.py`, and use fixtures from `tests/conftest.py` for isolated settings, in-memory Qdrant, mocked MinIO, and deterministic fake embeddings. Run `make test` before submitting. For V3 production-readiness changes, also run `uv run ruff check src/ tests/ scripts/` and `uv run mypy src tests`. Add tests when changing API routes, retrieval behavior, storage adapters, job queue behavior, security/configuration defaults, or evaluation utilities.

Docs-only changes should still be checked for stale commands and broken links. Do not update docs by copying old planning notes without verifying them against source code.

## Commit & Pull Request Guidelines

Recent history uses concise Conventional Commit-style subjects, for example `fix(core): extract pooler_output from CLIP feature returns`. Use `type(scope): summary` for non-merge commits when practical. Pull requests should include a short description, test results, linked issues, and screenshots or API examples for UI/API-visible changes.

## Security & Configuration Tips

Configuration is loaded from environment variables and optional `.env`. Do not commit secrets, production MinIO credentials, Qdrant API keys, large model files, generated datasets, local vector-store data, MinIO/Qdrant volumes, `.env`, or `.env.production`.

`docs/QA.md` and `docs/plans/*` are intentionally ignored/local. Do not force-add them unless the user explicitly asks.

When changing APIs, configuration, deployment behavior, indexing flow, evaluation scripts, or production operations, update the relevant files under `docs/EN/` and the root `README.md` in the same change.
