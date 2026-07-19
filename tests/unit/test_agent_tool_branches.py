"""Deterministic success and failure contracts for production Agent tools."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest

from academic_cluster.services.observability import (
    pop_current_project,
    push_current_project,
)
from academic_cluster.tools import agent_tools


class _Rows:
    def __init__(
        self,
        rows: list[Any] | None = None,
        row: Any = None,
    ) -> None:
        self.rows = rows or []
        self.row = row

    def fetchall(self) -> list[Any]:
        return self.rows

    def fetchone(self) -> Any:
        return self.row


@pytest.mark.asyncio
async def test_audit_wrapper_records_raised_and_cancelled_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    audits: list[dict[str, Any]] = []

    async def record(**kwargs: Any) -> None:
        audits.append(kwargs)

    async def fails() -> None:
        raise ValueError("invalid tool input")

    async def cancelled() -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(agent_tools, "_record_tool_audit", record)

    with pytest.raises(ValueError, match="invalid tool input"):
        await agent_tools._audited_agent_tool("analysis")(fails)()
    with pytest.raises(asyncio.CancelledError):
        await agent_tools._audited_agent_tool("writing")(cancelled)()

    assert [audit["status"] for audit in audits] == ["failed", "interrupted"]
    assert [audit["tool_name"] for audit in audits] == ["fails", "cancelled"]
    assert isinstance(audits[0]["error"], ValueError)
    assert isinstance(audits[1]["error"], asyncio.CancelledError)


@pytest.mark.asyncio
async def test_coverage_tool_handles_empty_and_small_project_sets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DB:
        def __init__(self) -> None:
            self.papers: list[dict[str, Any]] = []

        async def get_project_papers(
            self, project_id: str, *, limit: int
        ) -> list[dict[str, Any]]:
            assert (project_id, limit) == ("project-1", 500)
            return self.papers

    db = _DB()
    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: db,
    )
    token = push_current_project("project-1")
    try:
        empty = json.loads(
            await agent_tools.cluster_and_evaluate_coverage.ainvoke(
                {
                    "topic": "agent safety",
                    "target_papers": 10,
                    "embedding_model": "embedding-v1",
                }
            )
        )
        db.papers = [{"id": "paper-1"}, {"id": "paper-2"}]
        small = json.loads(
            await agent_tools.cluster_and_evaluate_coverage.ainvoke(
                {
                    "topic": "agent safety",
                    "target_papers": 10,
                    "embedding_model": "embedding-v1",
                }
            )
        )
    finally:
        pop_current_project(token)

    assert empty == {
        "cluster_count": 0,
        "total_papers": 0,
        "covered_aspects": [],
        "missing_aspects": ["agent safety"],
        "suggested_new_queries": ["agent safety"],
        "coverage_score": 0.0,
    }
    assert small["cluster_count"] == 1
    assert small["total_papers"] == 2
    assert small["coverage_score"] == 0.2


@pytest.mark.asyncio
async def test_coverage_tool_uses_model_scoped_knn_and_bounds_llm_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DB:
        def __init__(self) -> None:
            self.deleted: list[str] = []
            self.saved: list[dict[str, Any]] = []
            self.assignments: list[tuple[str, list[str]]] = []

        async def get_project_papers(
            self, project_id: str, *, limit: int
        ) -> list[dict[str, Any]]:
            assert (project_id, limit) == ("project-1", 500)
            return [
                {"id": "paper-1", "title": "Reliable Agent Planning"},
                {"id": "paper-2", "title": "Agent Tool Recovery"},
                {"id": "paper-3", "title": "Checkpoint Safety"},
            ]

        async def delete_project_clusters(self, project_id: str) -> None:
            self.deleted.append(project_id)

        async def save_cluster(self, cluster: dict[str, Any]) -> str:
            self.saved.append(cluster.copy())
            if len(self.saved) == 1:
                raise OSError("one cluster write failed")
            return "cluster-2"

        async def save_cluster_assignments(
            self, cluster_id: str, paper_ids: list[str]
        ) -> None:
            self.assignments.append((cluster_id, paper_ids))

    class _VectorStore:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def get_knn_graph(self, **kwargs: Any) -> list[dict[str, Any]]:
            self.calls.append(kwargs)
            return [{"source": "paper-1", "target": "paper-2", "weight": 0.9}]

    db = _DB()
    vector_store = _VectorStore()
    hybrid_calls: list[dict[str, Any]] = []

    def build_hybrid_graph(**kwargs: Any) -> object:
        hybrid_calls.append(kwargs)
        return object()

    clusters = [
        {"paper_ids": ["paper-1", "paper-2"]},
        {"paper_ids": ["paper-3"]},
    ]

    async def llm_response(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(
            content=[
                {
                    "text": json.dumps(
                        {
                            "covered_aspects": [" planning ", 7],
                            "missing_aspects": ["evaluation"],
                            "suggested_new_queries": ["agent evaluation"],
                            "coverage_score": 0.95,
                        }
                    )
                }
            ]
        )

    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.services.vector_store.get_vector_store",
        lambda: vector_store,
    )
    monkeypatch.setattr(
        "academic_cluster.tools.clustering.build_hybrid_graph",
        build_hybrid_graph,
    )
    monkeypatch.setattr(
        "academic_cluster.tools.clustering.community_detection",
        lambda **_kwargs: clusters,
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client.create_llm",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client.ainvoke_with_callbacks",
        llm_response,
    )
    token = push_current_project("project-1")
    try:
        raw = await agent_tools.cluster_and_evaluate_coverage.ainvoke(
            {
                "topic": "agent safety",
                "target_papers": 6,
                "embedding_model": "embedding-v2",
            }
        )
    finally:
        pop_current_project(token)

    result = json.loads(raw)
    assert vector_store.calls == [
        {
            "paper_ids": ["paper-1", "paper-2", "paper-3"],
            "k": 8,
            "threshold": 0.3,
            "model_name": "embedding-v2",
        }
    ]
    assert hybrid_calls[0]["core_paper_ids"] == [
        "paper-1",
        "paper-2",
        "paper-3",
    ]
    assert result["coverage_score"] == 0.5
    assert result["covered_aspects"] == ["planning"]
    assert result["missing_aspects"] == ["evaluation"]
    assert result["cluster_save_failures"] == 1
    assert db.deleted == ["project-1"]
    assert db.assignments == [("cluster-2", ["paper-3"])]


@pytest.mark.asyncio
async def test_knowledge_graph_tool_persists_only_resolved_relations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Session:
        async def execute(self, statement: Any, _params: dict[str, Any]) -> _Rows:
            sql = str(statement)
            if "SELECT DISTINCT unnest" in sql:
                return _Rows([])
            assert "SELECT normalized_name, id" in sql
            return _Rows(
                [
                    ("source entity", "entity-1"),
                    ("target entity", "entity-2"),
                ]
            )

    class _DB:
        def __init__(self) -> None:
            self.entities: list[dict[str, Any]] = []
            self.relations: list[dict[str, Any]] = []

        @asynccontextmanager
        async def session(self):
            yield _Session()

        async def save_kg_entities(self, entities: list[dict[str, Any]]) -> None:
            self.entities = entities

        async def save_kg_relations(self, relations: list[dict[str, Any]]) -> list[str]:
            self.relations = relations
            return ["relation-1"]

    db = _DB()

    async def extract(papers: list[dict[str, Any]], **_kwargs: Any) -> dict[str, Any]:
        if papers[0]["id"] == "paper-2":
            raise RuntimeError("one extraction failed")
        return {"entities": [{"name": "raw"}], "relations": [{"raw": True}]}

    def normalize(
        _entities: list[dict[str, Any]],
        _relations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "entities": [
                {"normalized_name": "source entity"},
                {"normalized_name": "target entity"},
            ],
            "relations": [
                {
                    "source": "Source Entity",
                    "target": "Target Entity",
                    "relation_type": "uses",
                },
                {
                    "source": "Missing Entity",
                    "target": "Target Entity",
                    "relation_type": "uses",
                },
            ],
        }

    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.agents.kg_extraction.extract_kg_from_papers_batch",
        extract,
    )
    monkeypatch.setattr(
        "academic_cluster.agents.kg_extraction.normalize_kg",
        normalize,
    )

    result = json.loads(
        await agent_tools.extract_knowledge_graph.ainvoke(
            {"papers_json": json.dumps([{"id": "paper-1"}, {"id": "paper-2"}])}
        )
    )

    assert result == {
        "entity_count": 2,
        "relation_count": 1,
        "status": "done",
        "processed_papers": 2,
        "truncated_papers": 0,
        "unresolved_relations": 1,
    }
    assert db.relations == [
        {
            "source": "Source Entity",
            "target": "Target Entity",
            "relation_type": "uses",
            "source_entity_id": "entity-1",
            "target_entity_id": "entity-2",
        }
    ]


@pytest.mark.asyncio
async def test_evidence_tool_reuses_real_cards_and_reports_save_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _DB:
        def __init__(self) -> None:
            self.cards: list[dict[str, Any]] = [
                {"paper_id": "paper-1", "claim": "existing claim", "confidence": 0.8}
            ]

        async def get_project_evidence_cards(
            self, project_id: str, *, paper_ids: list[str]
        ) -> list[dict[str, Any]]:
            assert project_id == "project-1"
            return [card for card in self.cards if card["paper_id"] in paper_ids]

        async def save_evidence_card(self, card: dict[str, Any]) -> str:
            if card["paper_id"] == "paper-3":
                raise OSError("write failed")
            self.cards.append(card.copy())
            return "evidence-2"

    async def generate(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {"paper_id": "paper-2", "claim": "new claim", "confidence": 0.9},
            {"paper_id": "paper-3", "claim": "failed claim", "confidence": 0.9},
            {
                "paper_id": "paper-4",
                "claim": "placeholder",
                "source_api": "fallback_missing_card",
            },
            {"claim": "missing paper id"},
        ]

    db = _DB()
    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.agents.evidence_generation.generate_evidence_cards_batch",
        generate,
    )
    token = push_current_project("project-1")
    try:
        result = json.loads(
            await agent_tools.generate_evidence.ainvoke(
                {
                    "papers_json": json.dumps(
                        [
                            {"id": "paper-1"},
                            {"id": "paper-2"},
                            {"id": "paper-3"},
                            {"id": "paper-4"},
                        ]
                    ),
                    "topic": "agent safety",
                }
            )
        )
    finally:
        pop_current_project(token)

    assert result["card_count"] == 2
    assert result["key_claims"] == ["existing claim", "new claim"]
    assert result["save_failures"] == 1
    assert result["fallback_count"] == 1


@pytest.mark.asyncio
async def test_model_json_tools_parse_content_blocks_and_wrappers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            [
                {
                    "text": "```json\n"
                    + json.dumps(
                        {
                            "identified_gaps": [],
                            "overall_completeness": 0.9,
                        }
                    )
                    + "\n```"
                }
            ],
            "prefix ```json "
            + json.dumps(
                {
                    "title": "Agent Review",
                    "sections": [{"title": "Planning", "target_words": 1000}],
                }
            )
            + " ``` suffix",
            [
                {"text": "<think>private reasoning</think>"},
                {
                    "text": json.dumps(
                        {
                            "overall_score": 84,
                            "strengths": ["grounded"],
                            "weaknesses": [],
                            "suggestions": [],
                        }
                    )
                },
            ],
        ]
    )

    async def invoke(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(content=next(responses))

    monkeypatch.setattr(
        "academic_cluster.services.llm_client.create_llm",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client.ainvoke_with_callbacks",
        invoke,
    )

    gaps = json.loads(
        await agent_tools.analyze_gaps_from_evidence.ainvoke(
            {
                "topic": "agent safety",
                "evidence_count": 3,
                "key_claims_json": "not-json",
            }
        )
    )
    outline = json.loads(
        await agent_tools.generate_outline.ainvoke(
            {
                "topic": "agent safety",
                "evidence_json": "not-json",
                "target_words": 3000,
            }
        )
    )
    review = json.loads(
        await agent_tools.peer_review_survey.ainvoke(
            {"review_text": "Supported statement [1].", "topic": "agent safety"}
        )
    )

    assert gaps["overall_completeness"] == 0.9
    assert outline["title"] == "Agent Review"
    assert outline["sections"][0]["title"] == "Planning"
    assert review["overall_score"] == 84


@pytest.mark.asyncio
async def test_section_tools_preserve_reference_prompt_and_content_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            [{"text": "Grounded analysis "}, {"text": "with evidence [2]."}],
            [{"text": "Revised grounded analysis [2]."}],
        ]
    )
    captured_messages: list[list[Any]] = []

    async def invoke(
        _llm: Any,
        messages: list[Any],
        **_kwargs: Any,
    ) -> SimpleNamespace:
        captured_messages.append(messages)
        return SimpleNamespace(content=next(responses))

    monkeypatch.setattr(
        "academic_cluster.services.llm_client.create_llm",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client.ainvoke_with_callbacks",
        invoke,
    )

    section = await agent_tools.write_section.ainvoke(
        {
            "topic": "agent safety",
            "section_title": "Recovery",
            "section_plan_json": json.dumps(
                {"target_words": 1000, "key_points": ["checkpoint recovery"]}
            ),
            "available_papers_json": json.dumps(
                [
                    {
                        "number": 2,
                        "title": "Reliable Recovery",
                        "authors": "Ada Lovelace, Grace Hopper",
                        "year": 2025,
                        "abstract": "Recovery evidence.",
                        "evidence_claims": ["Checkpoints recover safely."],
                    }
                ]
            ),
        }
    )
    revised = await agent_tools.revise_section.ainvoke(
        {
            "section_text": section,
            "revision_instructions": "Clarify recovery.",
        }
    )

    assert section == "Grounded analysis with evidence [2]."
    assert revised == "Revised grounded analysis [2]."
    write_prompt = str(captured_messages[0][1].content)
    assert "[2] Ada Lovelace, Grace Hopper. Reliable Recovery" in write_prompt
    assert "Checkpoints recover safely." in write_prompt
    assert "禁止使用“[7]提出/认为/发现”" in write_prompt
    revision_prompt = str(captured_messages[1][1].content)
    assert "保留已有作者与引用的绑定" in revision_prompt
    assert "已有研究提出……[N]" in revision_prompt


@pytest.mark.asyncio
async def test_structured_tool_errors_are_returned_or_raised_explicitly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_kg = json.loads(
        await agent_tools.extract_knowledge_graph.ainvoke({"papers_json": "not-json"})
    )
    invalid_evidence = json.loads(
        await agent_tools.generate_evidence.ainvoke(
            {"papers_json": "not-json", "topic": "agent safety"}
        )
    )
    assert invalid_kg["error"] == "invalid papers_json"
    assert invalid_evidence["error"] == "invalid papers_json"

    with pytest.raises(ValueError, match="at least one project reference"):
        await agent_tools.write_section.ainvoke(
            {
                "topic": "agent safety",
                "section_title": "Recovery",
                "section_plan_json": "{}",
                "available_papers_json": "[]",
            }
        )

    async def invalid_json(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(content="not json")

    monkeypatch.setattr(
        "academic_cluster.services.llm_client.create_llm",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client.ainvoke_with_callbacks",
        invalid_json,
    )
    with pytest.raises(RuntimeError, match="outline generation failed"):
        await agent_tools.generate_outline.ainvoke(
            {"topic": "agent safety", "evidence_json": "{}", "target_words": 3000}
        )
