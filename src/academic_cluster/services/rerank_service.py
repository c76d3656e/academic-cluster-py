"""Audited, bounded reranking for academic search results."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, cast

import httpx
import structlog

from .concurrency import BoundedFifoGate

logger = structlog.get_logger()


@dataclass(frozen=True)
class RerankOutcome:
    papers: list[dict[str, Any]]
    applied: bool
    provider_name: str | None = None
    model_name: str | None = None
    error: str | None = None


_request_gate: BoundedFifoGate | None = None
_request_gate_config: tuple[int, int, float] | None = None
_rate_windows: dict[str, deque[float]] = {}
_rate_locks: dict[str, asyncio.Lock] = {}


@asynccontextmanager
async def _request_slot(policy: Any) -> AsyncIterator[None]:
    global _request_gate, _request_gate_config

    config = (
        policy.rerank_max_concurrent_requests,
        policy.rerank_max_queued_requests,
        policy.rerank_queue_wait_timeout_seconds,
    )
    if _request_gate is None or _request_gate_config != config:
        _request_gate = BoundedFifoGate(capacity=config[0], max_waiters=config[1])
        _request_gate_config = config
    async with _request_gate.slot(timeout=config[2]):
        yield


async def _respect_rpm(provider: dict[str, Any], default_rpm: int) -> None:
    name = str(provider.get("name") or provider.get("api_url") or "rerank")
    try:
        rpm = max(1, int(provider.get("rpm_limit") or default_rpm))
    except (TypeError, ValueError):
        rpm = default_rpm
    lock = _rate_locks.setdefault(name, asyncio.Lock())
    window = _rate_windows.setdefault(name, deque())
    while True:
        async with lock:
            now = time.monotonic()
            while window and now - window[0] >= 60.0:
                window.popleft()
            if len(window) < rpm:
                window.append(now)
                return
            wait_seconds = max(0.01, 60.0 - (now - window[0]))
        await asyncio.sleep(wait_seconds)


def _document_text(paper: dict[str, Any]) -> str:
    title = " ".join(str(paper.get("title") or "").split())
    abstract = " ".join(str(paper.get("abstract") or "").split())
    return f"{title}\n{abstract}".strip()


def _endpoint(base_url: str) -> str:
    from ..api.admin.providers import _rerank_endpoint

    return _rerank_endpoint(base_url)


def _usage_tokens(payload: dict[str, Any]) -> int:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return 0
    for key in ("total_tokens", "prompt_tokens", "input_tokens"):
        value = usage.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            return max(0, value)
    return 0


def _apply_results(
    papers: list[dict[str, Any]],
    candidate_count: int,
    results: list[Any],
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    selected: set[int] = set()
    for item in results:
        if not isinstance(item, dict):
            raise RuntimeError("rerank provider returned a non-object result")
        index = item.get("index")
        score = item.get("relevance_score", item.get("score"))
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= candidate_count
            or index in selected
        ):
            raise RuntimeError("rerank provider returned an invalid result index")
        if not isinstance(score, int | float) or isinstance(score, bool):
            raise RuntimeError("rerank provider returned an invalid relevance score")
        selected.add(index)
        ranked.append({**papers[index], "rerank_score": float(score)})
    ranked.extend(papers[index] for index in range(candidate_count) if index not in selected)
    ranked.extend(papers[candidate_count:])
    return ranked


async def _audit_start(
    provider: dict[str, Any],
    *,
    query: str,
    document_count: int,
    timeout: float,
) -> tuple[Any | None, str | None]:
    from .observability import (
        get_current_agent_phase,
        get_current_execution,
        get_current_project,
    )

    project_id = get_current_project()
    execution_id = get_current_execution()
    if not project_id or not execution_id:
        return None, None
    from .crypto import mask_key
    from .database import get_database

    db = get_database()
    call_id = await db.create_llm_call(
        pipeline_run_id=None,
        node_execution_id=None,
        project_id=project_id,
        execution_id=execution_id,
        node_name=get_current_agent_phase() or "research",
        call_type="rerank",
        provider_name=str(provider.get("name") or "rerank"),
        model_name=str(provider.get("model") or ""),
        requested_model=str(provider.get("model") or ""),
        upstream_model=str(provider.get("model") or ""),
        api_base_url=str(provider.get("api_url") or ""),
        api_key_hint=mask_key(str(provider.get("api_key") or "")),
        input_preview=query[:2000],
        request_metadata={
            "query": query[:500],
            "document_count": document_count,
            "timeout_s": timeout,
        },
        status="running",
    )
    return db, call_id


async def _invoke_provider(
    provider: dict[str, Any],
    *,
    query: str,
    papers: list[dict[str, Any]],
    top_n: int,
    policy: Any,
) -> list[dict[str, Any]]:
    documents = [_document_text(paper) for paper in papers]
    db = None
    call_id = None
    started = time.monotonic()
    try:
        db, call_id = await _audit_start(
            provider,
            query=query,
            document_count=len(documents),
            timeout=policy.rerank_timeout_seconds,
        )
    except Exception as error:
        logger.warning("Failed to create rerank audit row", error=str(error))

    status_code: int | None = None
    try:
        await _respect_rpm(provider, policy.provider_default_rpm)
        async with _request_slot(policy):
            async with httpx.AsyncClient(timeout=policy.rerank_timeout_seconds) as client:
                response = await client.post(
                    _endpoint(str(provider.get("api_url") or "")),
                    headers={
                        "Authorization": f"Bearer {provider.get('api_key') or ''}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": str(provider.get("model") or ""),
                        "query": query,
                        "documents": documents,
                        "top_n": top_n,
                        "return_documents": False,
                    },
                )
            status_code = response.status_code
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise RuntimeError("rerank provider returned an invalid response")
        results = cast(list[dict[str, Any]], payload["results"])
        if db is not None and call_id is not None:
            tokens = _usage_tokens(payload)
            from ..api.admin.providers import get_provider_pricing

            input_price, _ = await get_provider_pricing(
                db,
                str(provider.get("name") or "rerank"),
                str(provider.get("model") or ""),
            )
            await db.finish_llm_call(
                call_id,
                status="success",
                prompt_tokens=tokens,
                completion_tokens=0,
                cost=(tokens * input_price) / 1_000_000,
                latency_ms=int((time.monotonic() - started) * 1000),
                output_preview=str(
                    [item.get("index") for item in results if isinstance(item, dict)]
                )[:2000],
                input_price_per_m=input_price,
                output_price_per_m=0,
            )
        return results
    except Exception as error:
        if db is not None and call_id is not None:
            await db.finish_llm_call(
                call_id,
                status="error",
                error_message=str(error)[:2000],
                http_status_code=status_code,
                latency_ms=int((time.monotonic() - started) * 1000),
            )
        raise


async def rerank_papers(
    query: str,
    papers: list[dict[str, Any]],
    *,
    policy: Any | None = None,
) -> RerankOutcome:
    """Rerank search results with failover and explicit fallback semantics."""

    if policy is None:
        from .runtime_policy import get_runtime_policy

        policy = await get_runtime_policy()
    if not policy.rerank_enabled or len(papers) < 2:
        return RerankOutcome(papers=list(papers), applied=False)

    from .provider_pool import get_rerank_providers

    providers = get_rerank_providers()
    if not providers:
        error = "rerank is enabled but no rerank Provider is available"
        if policy.rerank_failure_mode == "fail":
            raise RuntimeError(error)
        return RerankOutcome(papers=list(papers), applied=False, error=error)

    candidate_count = min(len(papers), policy.rerank_candidate_limit)
    top_n = min(candidate_count, policy.rerank_top_n)
    last_error: Exception | None = None
    attempts = max(1, policy.rerank_max_retries)
    for attempt in range(attempts):
        provider = providers[attempt % len(providers)]
        try:
            results = await _invoke_provider(
                provider,
                query=query,
                papers=papers[:candidate_count],
                top_n=top_n,
                policy=policy,
            )
            return RerankOutcome(
                papers=_apply_results(papers, candidate_count, results),
                applied=True,
                provider_name=str(provider.get("name") or "rerank"),
                model_name=str(provider.get("model") or ""),
            )
        except Exception as error:
            last_error = error
            logger.warning(
                "Rerank provider attempt failed",
                provider=provider.get("name"),
                attempt=attempt + 1,
                attempts=attempts,
                error=str(error),
            )
    message = f"rerank failed after {attempts} attempts: {last_error}"
    if policy.rerank_failure_mode == "fail":
        raise RuntimeError(message) from last_error
    return RerankOutcome(papers=list(papers), applied=False, error=message)
