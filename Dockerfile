# syntax=docker/dockerfile:1.7
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

WORKDIR /app

# Runtime deps for healthchecks and TLS package downloads.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv (Astral) — much faster Python package manager than pip.
COPY --from=ghcr.io/astral-sh/uv:0.7.9 /uv /usr/local/bin/uv

# Resolve dependencies first to maximise Docker layer caching.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Now install the project source.
COPY src/ src/
RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["clip-retrieval"]
