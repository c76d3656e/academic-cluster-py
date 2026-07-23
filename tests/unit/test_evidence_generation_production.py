"""Evidence extraction must preserve grounding and degrade per paper."""

from __future__ import annotations

import asyncio
import math
from types import SimpleNamespace
from typing import Any

import pytest

from academic_cluster.agents import evidence_generation


def test_create_evidence_agent_delegates_to_provider_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = object()
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> object:
        calls.append(kwargs)
        return model

    monkeypatch.setattr("academic_cluster.services.llm_client.create_llm", create)

    assert (
        evidence_generation.create_evidence_agent(
            model="ignored-project-model",
            temperature=0.35,
        )
        is model
    )
    assert calls == [{"temperature": 0.35}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    [
        [
            {"text": "prefix "},
            {
                "text": '{"claim":"claim","evidence_span":"span","confidence":0.8}',
            },
            {"text": " suffix"},
        ],
        '```json\n{"claim":"claim","evidence_span":"span","confidence":0.8}\n```',
    ],
)
async def test_generate_evidence_card_recovers_wrapped_json(
    monkeypatch: pytest.MonkeyPatch,
    content: Any,
) -> None:
    prompts: list[list[Any]] = []

    async def invoke(
        _agent: Any,
        messages: list[Any],
    ) -> SimpleNamespace:
        prompts.append(messages)
        return SimpleNamespace(content=content)

    monkeypatch.setattr(
        evidence_generation,
        "create_evidence_agent",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client.ainvoke_with_callbacks",
        invoke,
    )

    result = await evidence_generation.generate_evidence_card(
        {"id": "paper-1", "title": "Agent Paper", "abstract": "Evidence"},
        cluster_topics=["planning", "tools"],
    )

    assert result["paper_id"] == "paper-1"
    assert result["claim"] == "claim"
    prompt = str(prompts[0][1].content)
    assert "Agent Paper" in prompt
    assert "planning, tools" in prompt


@pytest.mark.asyncio
async def test_generate_evidence_card_rejects_irrecoverable_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def invoke(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(content="not JSON")

    monkeypatch.setattr(
        evidence_generation,
        "create_evidence_agent",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client.ainvoke_with_callbacks",
        invoke,
    )

    with pytest.raises(ValueError, match="invalid JSON"):
        await evidence_generation.generate_evidence_card(
            {"id": "paper-1", "title": "Agent Paper"}
        )


def test_normalize_evidence_card_enforces_grounding_and_bounds_fields() -> None:
    paper = {
        "id": "paper-1",
        "title": "  Agent   Paper  ",
        "authors": ["Researcher"],
        "publication_date": "2025-04-03",
        "abstract": "Grounded abstract.",
    }

    assert (
        evidence_generation.normalize_evidence_card(None, paper)["source_api"]
        == "fallback_missing_card"
    )
    assert (
        evidence_generation.normalize_evidence_card(
            {"claim": "claim without evidence"}, paper
        )["source_api"]
        == "fallback_missing_card"
    )

    normalized = evidence_generation.normalize_evidence_card(
        {
            "key_finding": "  Supported   claim  ",
            "evidence_span": "  Direct   evidence  ",
            "method": " method " * 100,
            "metric": "accuracy",
            "limitation": " limitation " * 100,
            "confidence": math.nan,
            "source_api": "  model-output ",
        },
        paper,
    )

    assert normalized["paper_id"] == "paper-1"
    assert normalized["title"] == "Agent Paper"
    assert normalized["authors"] == ["Researcher"]
    assert normalized["year"] == 2025
    assert normalized["claim"] == "Supported claim"
    assert normalized["evidence_span"] == "Direct evidence"
    assert len(normalized["method"]) == 240
    assert len(normalized["limitation"]) == 240
    assert normalized["confidence"] == 0.0
    assert normalized["source_api"] == "model-output"


def test_fallback_card_uses_safe_title_year_and_confidence() -> None:
    card = evidence_generation.fallback_missing_card(
        {
            "id": "paper-2",
            "title": "",
            "abstract": "  Fallback   evidence  ",
            "year": "invalid",
            "publication_date": "2024-01-01",
        }
    )

    assert card["title"] == "Untitled"
    assert card["year"] == 2024
    assert card["claim"] == "Fallback evidence"
    assert card["confidence"] == 0.05
    assert evidence_generation._clamp_confidence("invalid") == 0.0
    assert evidence_generation._clamp_confidence(-2) == 0.0
    assert evidence_generation._clamp_confidence(2) == 1.0


@pytest.mark.asyncio
async def test_batch_preserves_order_and_degrades_each_failed_or_invalid_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    max_active = 0
    topic_calls: list[tuple[str, list[str] | None]] = []

    async def generate(
        paper: dict[str, Any],
        cluster_topics: list[str] | None = None,
    ) -> dict[str, Any]:
        nonlocal active, max_active
        topic_calls.append((str(paper["id"]), cluster_topics))
        active += 1
        max_active = max(max_active, active)
        try:
            await asyncio.sleep(0)
            if paper["id"] == "paper-2":
                raise RuntimeError("provider failure")
            if paper["id"] == "paper-3":
                return {"claim": "missing evidence"}
            return {
                "claim": "real claim",
                "evidence_span": "real evidence",
                "confidence": 0.9,
            }
        finally:
            active -= 1

    monkeypatch.setattr(evidence_generation, "generate_evidence_card", generate)
    progress: list[tuple[int, int]] = []
    papers = [
        {"id": "paper-1", "title": "One", "abstract": "Abstract one"},
        {"id": "paper-2", "title": "Two", "abstract": "Abstract two"},
        {"id": "paper-3", "title": "Three", "abstract": "Abstract three"},
    ]

    cards = await evidence_generation.generate_evidence_cards_batch(
        papers,
        cluster_topics={"paper-1": ["planning"]},
        concurrency=2,
        timeout_s=2,
        progress_callback=lambda completed, total: progress.append((completed, total)),
    )

    assert [card["paper_id"] for card in cards] == [
        "paper-1",
        "paper-2",
        "paper-3",
    ]
    assert cards[0]["source_api"] == "llm"
    assert cards[1]["source_api"] == "fallback_missing_card"
    assert cards[2]["source_api"] == "fallback_missing_card"
    assert max_active == 2
    assert topic_calls[0] == ("paper-1", ["planning"])
    assert progress == [(1, 3), (2, 3), (3, 3)]
