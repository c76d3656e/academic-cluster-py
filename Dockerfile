# syntax=docker/dockerfile:1
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.7-python3.12-bookworm-slim@sha256:0213115f0f4e8e3a3416441723526f0b3197ef3f6df69916397a9195d1fc7774
ARG PYTHON_IMAGE=python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de
FROM ${UV_IMAGE} AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_LINK_MODE=copy

# Layer 1: 安装第三方依赖（pyproject.toml / uv.lock 不变时此层命中缓存）
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --no-install-project

# Layer 2: 复制源码并安装项目本体（源码变动只重跑这一层）
COPY src/ src/
COPY pyproject.toml uv.lock README.md ./
COPY scripts/migrate_agent_tables.sql scripts/migrate_agent_tables.sql
COPY scripts/migrate_security.sql scripts/migrate_security.sql

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

FROM ${PYTHON_IMAGE} AS production

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

WORKDIR /app

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/pyproject.toml /app/pyproject.toml

COPY --chown=appuser:appuser src/ src/
COPY --chown=appuser:appuser jcrdata/ jcrdata/
COPY --chown=appuser:appuser scripts/migrate_agent_tables.sql scripts/migrate_agent_tables.sql
COPY --chown=appuser:appuser scripts/migrate_security.sql scripts/migrate_security.sql

RUN mkdir -p data/raw data/processed data/embeddings logs && \
    chown -R appuser:appuser data logs

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANGGRAPH_STRICT_MSGPACK=true \
    PYTHONPATH=/app/src

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

EXPOSE 8000

CMD ["uvicorn", "academic_cluster.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
