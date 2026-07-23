"""Structured extraction agents must reject valid JSON with the wrong root type."""

from types import SimpleNamespace
from typing import Any

import pytest

from academic_cluster.agents import evidence_generation, kg_extraction


def test_kg_parser_rejects_non_object_json() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        kg_extraction.parse_kg_response("[]")


@pytest.mark.asyncio
async def test_evidence_agent_rejects_non_object_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def invoke(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(content="[]")

    monkeypatch.setattr(
        evidence_generation,
        "create_evidence_agent",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client.ainvoke_with_callbacks",
        invoke,
    )

    with pytest.raises(ValueError, match="JSON object"):
        await evidence_generation.generate_evidence_card(
            {"id": "paper-1", "title": "Paper", "abstract": "Evidence"}
        )
