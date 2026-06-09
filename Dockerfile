# Multi-stage build for academic-cluster
FROM python:3.10-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:$PATH"

# Builder stage
FROM base as builder

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.toml requirements.txt ./

# Create virtual environment and install dependencies
RUN uv venv .venv && \
    . .venv/bin/activate && \
    uv pip install --no-cache-dir -r requirements.txt

# Production stage
FROM python:3.10-slim as production

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv .venv

# Copy application code
COPY src/ src/
COPY pyproject.toml ./

# Create data directories
RUN mkdir -p data/raw data/processed data/embeddings logs && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Activate virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Expose port
EXPOSE 8000

# Run application
CMD ["uvicorn", "academic_cluster.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
