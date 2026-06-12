# ---- Build stage ----
FROM ghcr.io/astral-sh/uv:0.7-python3.12-bookworm-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖定义，利用 Docker layer cache
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace

# 复制源码并安装项目本身
COPY src/ src/
COPY pyproject.toml README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---- Production stage ----
FROM python:3.12-slim AS production

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

WORKDIR /app

# 从 builder 复制已安装好的虚拟环境
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/pyproject.toml /app/pyproject.toml

# 复制源码
COPY --chown=appuser:appuser src/ src/

# 创建数据目录
RUN mkdir -p data/raw data/processed data/embeddings logs && \
    chown -R appuser:appuser /app

# 设置虚拟环境 PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src

USER appuser

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]

EXPOSE 8000

CMD ["uvicorn", "academic_cluster.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
