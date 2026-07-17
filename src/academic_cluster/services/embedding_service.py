"""Project-paper embedding generation used by the agent analysis phase."""

from __future__ import annotations

import asyncio
import math
from typing import Any

import structlog

logger = structlog.get_logger()

EMBEDDING_DIMENSIONS = 1024


def get_active_embedding_model() -> str:
    """Return the model group used by the current embedding pool."""

    from .provider_pool import get_embedding_pool

    model_name = get_embedding_pool().get_model_name().strip()
    if not model_name:
        raise RuntimeError("embedding pool returned an empty model name")
    return model_name


def _validated_embedding(values: Any) -> list[float]:
    """Validate vectors before they can enter the fixed pgvector column."""

    if not isinstance(values, list):
        raise RuntimeError("embedding provider returned a non-list vector")
    if any(isinstance(value, bool) for value in values):
        raise RuntimeError("embedding provider returned non-numeric values")
    try:
        embedding = [float(value) for value in values]
    except (TypeError, ValueError) as error:
        raise RuntimeError("embedding provider returned non-numeric values") from error
    if len(embedding) != EMBEDDING_DIMENSIONS:
        raise RuntimeError(
            "embedding provider returned an incompatible vector dimension: "
            f"{len(embedding)}/{EMBEDDING_DIMENSIONS}"
        )
    if not all(math.isfinite(value) for value in embedding):
        raise RuntimeError("embedding provider returned non-finite values")
    return embedding


async def _generate_embedding(
    text: str,
    timeout: float,
    model_name: str,
) -> list[float]:
    from .provider_pool import get_embedding_pool

    pool = get_embedding_pool()
    response = await asyncio.wait_for(
        pool.router.aembedding(model=model_name, input=[text]),
        timeout=timeout,
    )
    data = getattr(response, "data", None)
    if not isinstance(data, list) or not data:
        raise RuntimeError("embedding provider returned an empty vector")
    item = data[0]
    # LiteLLM returns ``Embedding`` model objects in production, while test
    # doubles and some compatible routers return plain dictionaries.
    values = (
        item.get("embedding")
        if isinstance(item, dict)
        else getattr(item, "embedding", None)
    )
    return _validated_embedding(values)


async def ensure_paper_embeddings(
    papers: list[dict[str, Any]],
    *,
    model_name: str | None = None,
    concurrency: int = 10,
    timeout: float = 60.0,
) -> int:
    """Ensure every supplied project paper has a persisted embedding."""

    from .cache import get_cache
    from .database import get_database
    from .vector_store import get_vector_store

    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for paper in papers:
        paper_id = str(paper.get("id") or paper.get("paper_id") or "").strip()
        if not paper_id or paper_id in seen:
            continue
        seen.add(paper_id)
        text = f"{paper.get('title') or ''} {paper.get('abstract') or ''}".strip()
        if text:
            normalized.append((paper_id, text))
    if not normalized:
        return 0

    resolved_model = (model_name or get_active_embedding_model()).strip()
    if not resolved_model:
        raise RuntimeError("embedding model name cannot be empty")

    db = get_database()
    existing = await db.get_existing_embedding_paper_ids(
        [paper_id for paper_id, _text in normalized],
        model_name=resolved_model,
    )
    missing = [
        (paper_id, text) for paper_id, text in normalized if paper_id not in existing
    ]
    if not missing:
        return len(normalized)

    semaphore = asyncio.Semaphore(max(1, concurrency))
    cache = get_cache()

    async def embed_one(paper_id: str, text: str) -> tuple[str, list[float]]:
        async with semaphore:
            cached = await cache.get_embedding(paper_id, resolved_model)
            if cached:
                try:
                    return paper_id, _validated_embedding(cached)
                except RuntimeError as error:
                    logger.warning(
                        "Ignoring invalid cached embedding",
                        paper_id=paper_id,
                        model_name=resolved_model,
                        error=str(error),
                    )
            embedding = await _generate_embedding(text, timeout, resolved_model)
            await cache.set_embedding(paper_id, resolved_model, embedding)
            return paper_id, embedding

    tasks: list[asyncio.Task[tuple[str, list[float]]]] = []
    async with asyncio.TaskGroup() as task_group:
        tasks = [
            task_group.create_task(
                embed_one(paper_id, text),
                name=f"agent-embedding:{paper_id}",
            )
            for paper_id, text in missing
        ]
    generated = [task.result() for task in tasks]
    await get_vector_store().add_embeddings(
        paper_ids=[paper_id for paper_id, _embedding in generated],
        embeddings=[embedding for _paper_id, embedding in generated],
        model_name=resolved_model,
    )
    logger.info(
        "Project paper embeddings ready",
        total=len(normalized),
        reused=len(existing),
        generated=len(generated),
        model_name=resolved_model,
    )
    return len(normalized)
