"""Knowledge-graph extraction parsing and normalization production contracts."""

from __future__ import annotations

import json
import math
from types import SimpleNamespace
from typing import Any

import pytest

from academic_cluster.agents import kg_extraction


def test_parse_kg_response_repairs_model_wrappers_and_illegal_json() -> None:
    response = """<think>private reasoning</think>
```json
{"entities": [{"name": "Agent\\%System"}], "relations": [],}
```"""

    parsed = kg_extraction.parse_kg_response(response)

    assert parsed == {
        "entities": [{"name": "Agent%System"}],
        "relations": [],
    }

    with pytest.raises(ValueError, match="invalid JSON"):
        kg_extraction.parse_kg_response("not a JSON payload")


def test_normalize_kg_merges_entities_and_filters_invalid_relations() -> None:
    paper_1 = "11111111-1111-1111-1111-111111111111"
    paper_2 = "22222222-2222-2222-2222-222222222222"
    normalized = kg_extraction.normalize_kg(
        [
            {
                "name": "Large Language Model",
                "type": "model",
                "paper_ids": [paper_1],
                "aliases": ["LLM"],
                "confidence": 0.4,
                "evidence": "initial",
            },
            {
                "name": " large-language model ",
                "entity_type": "finding",
                "paper_ids": [paper_2, "invalid"],
                "aliases": ["LLM", "language model"],
                "confidence": 0.9,
                "evidence": "stronger",
            },
            {
                "name": "Agent Benchmark",
                "entity_type": "benchmark",
                "confidence": math.nan,
            },
            {"name": "---", "entity_type": "Concept"},
            {"name": "", "entity_type": "Concept"},
        ],
        [
            {
                "source": "Large Language Model",
                "target": "Agent Benchmark",
                "type": "tested_on",
                "paper_ids": [paper_1, "invalid"],
                "confidence": 1.5,
                "evidence": "evaluation",
            },
            {
                "source": "large-language model",
                "target": "Agent Benchmark",
                "relation_type": "evaluated_on",
                "confidence": 0.2,
            },
            {
                "source": "Agent Benchmark",
                "target": "Agent Benchmark",
                "relation_type": "uses",
            },
            {
                "source": "Missing",
                "target": "Agent Benchmark",
                "relation_type": "uses",
            },
            {
                "source": "Large Language Model",
                "target": "Agent Benchmark",
                "relation_type": "invented_relation",
            },
            {"source": "", "target": "Agent Benchmark", "relation_type": "uses"},
        ],
    )

    assert normalized["stats"] == {
        "entity_count": 2,
        "relation_count": 1,
        "dropped_relations": 4,
    }
    model = normalized["entities"][0]
    assert model["normalized_name"] == "large language model"
    assert model["entity_type"] == "Concept"
    assert model["confidence"] == 0.9
    assert model["paper_ids"] == [paper_1, paper_2]
    assert model["aliases"] == ["LLM", "language model"]
    assert model["evidence"] == "stronger"
    relation = normalized["relations"][0]
    assert relation["relation_type"] == "evaluated_on"
    assert relation["paper_ids"] == [paper_1]
    assert relation["confidence"] == 1.0


def test_normalize_kg_tolerates_null_collection_fields() -> None:
    normalized = kg_extraction.normalize_kg(
        [
            {
                "name": "Agent",
                "entity_type": "Concept",
                "paper_ids": None,
                "aliases": None,
                "evidence": None,
            },
            {"name": "Tool", "entity_type": "Material"},
        ],
        [
            {
                "source": "Agent",
                "target": "Tool",
                "relation_type": "uses",
                "paper_ids": None,
                "evidence": None,
            }
        ],
    )

    assert normalized["stats"] == {
        "entity_count": 2,
        "relation_count": 1,
        "dropped_relations": 0,
    }


@pytest.mark.asyncio
async def test_extract_batch_builds_bounded_prompt_and_parses_content_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[Any], dict[str, Any]]] = []

    async def call(messages: list[Any], **kwargs: Any) -> SimpleNamespace:
        calls.append((messages, kwargs))
        return SimpleNamespace(
            content=[
                {"text": json.dumps({"entities": [{"name": "Agent"}]})},
                {"text": ""},
            ]
        )

    monkeypatch.setattr(kg_extraction, "_call_llm_with_retry", call)

    result = await kg_extraction.extract_kg_from_papers_batch(
        [
            {"id": "paper-1", "title": "Agent paper", "abstract": "Evidence"},
            {"id": "paper-2", "title": "No abstract", "abstract": None},
        ],
        max_entities_per_paper=4,
        max_relations_per_paper=3,
    )

    assert result == {"entities": [{"name": "Agent"}]}
    messages, kwargs = calls[0]
    assert kwargs == {"max_retries": 3, "temperature": 0.1, "timeout": 300}
    prompt = str(messages[1].content)
    assert "ID: paper-1" in prompt
    assert "Title: Agent paper" in prompt
    assert "ID: paper-2" in prompt
    assert "up to 4 entities" in prompt
    assert "up to 3 relations" in prompt


@pytest.mark.asyncio
async def test_llm_retry_boundary_uses_provider_client_once_on_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = object()
    create_calls: list[dict[str, Any]] = []
    invoke_calls: list[tuple[Any, list[Any]]] = []

    def create(**kwargs: Any) -> object:
        create_calls.append(kwargs)
        return model

    async def invoke(llm: Any, messages: list[Any]) -> SimpleNamespace:
        invoke_calls.append((llm, messages))
        return SimpleNamespace(content="{}")

    monkeypatch.setattr("academic_cluster.services.llm_client.create_llm", create)
    monkeypatch.setattr(
        "academic_cluster.services.llm_client.ainvoke_with_callbacks",
        invoke,
    )

    response = await kg_extraction._call_llm_with_retry(
        ["message"],
        max_retries=1,
        temperature=0.25,
        timeout=1,
    )

    assert response.content == "{}"
    assert create_calls == [{"temperature": 0.25, "max_tokens": None}]
    assert invoke_calls == [(model, ["message"])]
