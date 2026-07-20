"""Rerank routing, fallback and ordering contracts."""

from types import SimpleNamespace
from typing import Any

import pytest

from academic_cluster.services import provider_pool, rerank_service


def _policy(**overrides: Any) -> SimpleNamespace:
    values = {
        "rerank_enabled": True,
        "rerank_candidate_limit": 3,
        "rerank_top_n": 2,
        "rerank_max_retries": 2,
        "rerank_failure_mode": "passthrough",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _papers() -> list[dict[str, Any]]:
    return [
        {"id": "p0", "title": "zero"},
        {"id": "p1", "title": "one"},
        {"id": "p2", "title": "two"},
        {"id": "p3", "title": "outside candidate window"},
    ]


async def test_rerank_normal_reorders_results_and_preserves_remaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers = [{"name": "ranker", "model": "model"}]
    monkeypatch.setattr(provider_pool, "get_rerank_providers", lambda: providers)

    async def invoke(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {"index": 2, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.7},
        ]

    monkeypatch.setattr(rerank_service, "_invoke_provider", invoke)
    outcome = await rerank_service.rerank_papers("query", _papers(), policy=_policy())

    assert outcome.applied is True
    assert outcome.provider_name == "ranker"
    assert [paper["id"] for paper in outcome.papers] == ["p2", "p0", "p1", "p3"]
    assert outcome.papers[0]["rerank_score"] == 0.9


async def test_rerank_edge_without_provider_preserves_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider_pool, "get_rerank_providers", lambda: [])

    outcome = await rerank_service.rerank_papers("query", _papers(), policy=_policy())

    assert outcome.applied is False
    assert [paper["id"] for paper in outcome.papers] == ["p0", "p1", "p2", "p3"]
    assert "no rerank Provider" in str(outcome.error)


async def test_rerank_failure_passthrough_exhausts_configured_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers = [{"name": "ranker-a"}, {"name": "ranker-b"}]
    monkeypatch.setattr(provider_pool, "get_rerank_providers", lambda: providers)
    attempts: list[str] = []

    async def invoke(provider: dict[str, Any], **_kwargs: Any) -> list[dict[str, Any]]:
        attempts.append(str(provider["name"]))
        raise TimeoutError("upstream timeout")

    monkeypatch.setattr(rerank_service, "_invoke_provider", invoke)
    outcome = await rerank_service.rerank_papers("query", _papers(), policy=_policy())

    assert outcome.applied is False
    assert attempts == ["ranker-a", "ranker-b"]
    assert "upstream timeout" in str(outcome.error)


async def test_rerank_regression_strict_mode_propagates_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        provider_pool,
        "get_rerank_providers",
        lambda: [{"name": "ranker"}],
    )

    async def invoke(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        raise RuntimeError("malformed response")

    monkeypatch.setattr(rerank_service, "_invoke_provider", invoke)
    with pytest.raises(RuntimeError, match="malformed response"):
        await rerank_service.rerank_papers(
            "query",
            _papers(),
            policy=_policy(rerank_failure_mode="fail", rerank_max_retries=1),
        )
