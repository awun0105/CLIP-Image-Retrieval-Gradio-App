.PHONY: install dev sync lock run test lint format docker-build docker-up docker-down docker-logs prod-config prod-build prod-up prod-down prod-logs migrate qdrant-index-config

PROD_ENV_FILE ?= .env.production

# --- Local development (uv) ---

install:
	uv sync --no-dev

dev:
	uv sync

sync: dev

lock:
	uv lock

run:
	uv run clip-retrieval

test:
	uv run pytest tests/ -v

lint:
	uv run ruff check src/ tests/

format:
	uv run ruff format src/ tests/

# --- Docker ---

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f app

prod-config:
	PROD_ENV_FILE=$(PROD_ENV_FILE) docker compose --env-file $(PROD_ENV_FILE) -f docker-compose.prod.yml config

prod-build:
	PROD_ENV_FILE=$(PROD_ENV_FILE) docker compose --env-file $(PROD_ENV_FILE) -f docker-compose.prod.yml build

prod-up:
	PROD_ENV_FILE=$(PROD_ENV_FILE) docker compose --env-file $(PROD_ENV_FILE) -f docker-compose.prod.yml up -d

prod-down:
	PROD_ENV_FILE=$(PROD_ENV_FILE) docker compose --env-file $(PROD_ENV_FILE) -f docker-compose.prod.yml down

prod-logs:
	PROD_ENV_FILE=$(PROD_ENV_FILE) docker compose --env-file $(PROD_ENV_FILE) -f docker-compose.prod.yml logs -f app worker

# --- Migration ---

migrate:
	uv run python scripts/migrate_to_qdrant.py

qdrant-index-config:
	uv run python scripts/update_qdrant_index_config.py
