"""Project-paper embedding generation used by the agent analysis phase."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog

from .concurrency import BoundedFifoGate

logger = structlog.get_logger()

EMBEDDING_DIMENSIONS = 1024
_embedding_request_gate: BoundedFifoGate | None = None
_embedding_request_gate_config: tuple[int, int, float] | None = None


def _get_embedding_request_gate() -> tuple[BoundedFifoGate, float]:
    """Return the shared capacity boundary for every embedding execution."""

    global _embedding_request_gate, _embedding_request_gate_config

    from ..config import get_settings

    settings = get_settings()
    config = (
        settings.embedding_max_concurrent_requests,
        settings.embedding_max_queued_requests,
        settings.embedding_queue_wait_timeout_seconds,
    )
    if _embedding_request_gate is None or config != _embedding_request_gate_config:
        _embedding_request_gate = BoundedFifoGate(
            capacity=config[0], max_waiters=config[1]
        )
        _embedding_request_gate_config = config
        logger.info(
            "Embedding request gate configured",
            capacity=config[0],
            max_waiters=config[1],
            queue_wait_timeout_seconds=config[2],
        )
    return _embedding_request_gate, config[2]


@asynccontextmanager
async def _embedding_request_slot() -> AsyncIterator[None]:
    gate, wait_timeout = _get_embedding_request_gate()
    async with gate.slot(timeout=wait_timeout):
        yield


def _object_field(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _key_hint(value: Any) -> str | None:
    if value is None:
        return None
    raw = str(value)
    if not raw:
        return None
    return "****" if len(raw) <= 4 else f"***{raw[-4:]}"


def _embedding_deployment(
    pool: Any,
    model_name: str,
    response: Any | None = None,
) -> dict[str, str | None]:
    """Resolve provider metadata without exposing the configured API key."""

    deployment = None
    hidden = _object_field(response, "_hidden_params", {}) if response else {}
    model_id = hidden.get("model_id") if isinstance(hidden, dict) else None
    get_deployment = getattr(pool.router, "get_deployment", None)
    if isinstance(model_id, str) and model_id and callable(get_deployment):
        try:
            deployment = get_deployment(model_id)
        except Exception:
            deployment = None

    if deployment is None:
        for candidate in getattr(pool, "deployments", []) or []:
            if str(_object_field(candidate, "model_name", "")) == model_name:
                deployment = candidate
                break
        if deployment is None:
            deployments = getattr(pool, "deployments", []) or []
            deployment = deployments[0] if deployments else {}

    model_info = _object_field(deployment, "model_info", {}) or {}
    params = _object_field(deployment, "litellm_params", {}) or {}
    provider_alias = str(_object_field(model_info, "provider_alias", "") or "")
    upstream_model = str(_object_field(params, "model", "") or model_name)
    api_base_url = str(
        _object_field(params, "api_base", "")
        or (hidden.get("api_base", "") if isinstance(hidden, dict) else "")
        or ""
    )
    return {
        "provider_name": provider_alias or "embedding",
        "upstream_model": upstream_model,
        "api_base_url": api_base_url,
        "api_key_hint": _key_hint(_object_field(params, "api_key")),
    }


def _embedding_usage(response: Any) -> int:
    usage = _object_field(response, "usage", {}) or {}
    prompt_tokens = _object_field(usage, "prompt_tokens", None)
    if prompt_tokens is None:
        prompt_tokens = _object_field(usage, "input_tokens", None)
    if prompt_tokens is None:
        prompt_tokens = _object_field(usage, "total_tokens", 0)
    try:
        return max(0, int(prompt_tokens or 0))
    except (TypeError, ValueError):
        return 0


async def _finish_embedding_audit(
    db: Any,
    call_id: str | None,
    **values: Any,
) -> None:
    if not call_id:
        return
    try:
        await db.finish_llm_call(call_id=call_id, **values)
    except Exception as error:
        logger.warning(
            "Failed to finish embedding call audit row",
            call_id=call_id,
            error=str(error),
        )


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
    from .database import get_database
    from .observability import (
        get_current_agent_phase,
        get_current_execution,
        get_current_project,
    )
    from .provider_pool import get_embedding_pool

    pool = get_embedding_pool()
    deployment = _embedding_deployment(pool, model_name)
    project_id = get_current_project()
    execution_id = get_current_execution()
    node_name = get_current_agent_phase() or ("agent" if execution_id else "unknown")
    db = None
    call_id = None

    if project_id and execution_id:
        try:
            db = get_database()
            call_id = await db.create_llm_call(
                pipeline_run_id=None,
                node_execution_id=None,
                project_id=project_id,
                execution_id=execution_id,
                node_name=node_name,
                call_type="embedding",
                provider_name=deployment["provider_name"] or "embedding",
                model_name=model_name,
                requested_model=model_name,
                upstream_model=deployment["upstream_model"],
                api_base_url=deployment["api_base_url"],
                api_key_hint=deployment["api_key_hint"],
                input_preview=text[:2000],
                request_metadata={
                    "node_name": node_name,
                    "execution_id": execution_id,
                    "timeout_s": timeout,
                    "input_count": 1,
                    "input_characters": len(text),
                    "dimensions": EMBEDDING_DIMENSIONS,
                },
                status="running",
            )
        except Exception as error:
            logger.warning(
                "Failed to create embedding call audit row",
                node=node_name,
                error=str(error),
            )

    started = time.monotonic()
    try:
        async with _embedding_request_slot():
            response = await asyncio.wait_for(
                pool.router.aembedding(model=model_name, input=[text]),
                timeout=timeout,
            )
    except asyncio.CancelledError:
        if db is not None:
            await _finish_embedding_audit(
                db,
                call_id,
                status="error",
                error_message="Embedding call cancelled",
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        raise
    except Exception as error:
        if db is not None:
            await _finish_embedding_audit(
                db,
                call_id,
                status="error",
                error_message=str(error),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        raise

    data = getattr(response, "data", None)
    if not isinstance(data, list) or not data:
        empty_response_error = RuntimeError(
            "embedding provider returned an empty vector"
        )
        if db is not None:
            await _finish_embedding_audit(
                db,
                call_id,
                status="error",
                error_message=str(empty_response_error),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        raise empty_response_error
    item = data[0]
    # LiteLLM returns ``Embedding`` model objects in production, while test
    # doubles and some compatible routers return plain dictionaries.
    values = (
        item.get("embedding")
        if isinstance(item, dict)
        else getattr(item, "embedding", None)
    )
    try:
        embedding = _validated_embedding(values)
    except RuntimeError as error:
        if db is not None:
            await _finish_embedding_audit(
                db,
                call_id,
                status="error",
                error_message=str(error),
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        raise

    if db is not None:
        resolved = _embedding_deployment(pool, model_name, response)
        prompt_tokens = _embedding_usage(response)
        input_price = 0.0
        try:
            from ..api.admin.providers import get_provider_pricing

            input_price, _ = await get_provider_pricing(
                db,
                str(resolved["provider_name"] or "embedding"),
                model_name,
            )
        except Exception:
            input_price = 0.0
        await _finish_embedding_audit(
            db,
            call_id,
            status="success",
            prompt_tokens=prompt_tokens,
            completion_tokens=0,
            cost=(prompt_tokens * input_price) / 1_000_000,
            latency_ms=int((time.monotonic() - started) * 1000),
            model_name=model_name,
            upstream_model=resolved["upstream_model"],
            provider_name=resolved["provider_name"],
            api_base_url=resolved["api_base_url"],
            api_key_hint=resolved["api_key_hint"],
            input_price_per_m=input_price,
            output_price_per_m=0.0,
        )
    return embedding


async def ensure_paper_embeddings(
    papers: list[dict[str, Any]],
    *,
    model_name: str | None = None,
    concurrency: int | None = None,
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

    from ..config import get_settings

    per_run_concurrency = (
        get_settings().embedding_max_concurrent_requests
        if concurrency is None
        else concurrency
    )
    semaphore = asyncio.Semaphore(max(1, per_run_concurrency))
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
