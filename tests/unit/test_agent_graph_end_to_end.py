"""Run the compiled production graph through every phase with bounded fakes."""

from __future__ import annotations

import json
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from academic_cluster.agents import (
    agent_graph,
    peer_review_team,
    research_team,
    writing_team,
)
from academic_cluster.services import (
    citation_planner,
    embedding_service,
    section_evidence_planner,
)
from academic_cluster.tools import agent_tools


class _Tool:
    def __init__(self, output: Any) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(self, payload: dict[str, Any]) -> Any:
        self.calls.append(payload)
        return self.output(payload) if callable(self.output) else self.output


class _Database:
    def __init__(self) -> None:
        self.decisions: list[str] = []
        self.project_statuses: list[str] = []
        self.final_snapshots: list[dict[str, Any]] = []
        self.outlines: list[dict[str, Any]] = []

    async def record_agent_decision(self, **kwargs: Any) -> str:
        self.decisions.append(str(kwargs["decision"]))
        return f"decision-{len(self.decisions)}"

    async def update_project_status(self, project_id: str, status: str) -> None:
        del project_id
        self.project_statuses.append(status)

    async def save_outline(self, data: dict[str, Any]) -> str:
        self.outlines.append(data)
        return str(data["id"])

    async def save_written_section(self, data: dict[str, Any]) -> str:
        return str(data["section_id"])

    async def save_pipeline_checkpoint(self, data: dict[str, Any]) -> str:
        self.final_snapshots.append(data)
        return "checkpoint-1"


async def test_compiled_production_graph_runs_all_phases(
    monkeypatch,
) -> None:
    database = _Database()
    papers = [
        {
            "id": "paper-1",
            "title": "Agent planning foundations",
            "abstract": "Evidence for planning agents.",
            "year": 2025,
        },
        {
            "id": "paper-2",
            "title": "Tool-using language models",
            "abstract": "Evidence for tool use.",
            "year": 2024,
        },
    ]

    async def fake_research(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {"papers": papers, "status": "completed", "queries_used": ["topic"]}

    async def fake_embeddings(
        input_papers: list[dict[str, Any]],
        *,
        model_name: str,
    ) -> int:
        assert model_name == "embedding-test-model"
        return len(input_papers)

    async def fake_writing(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "outline": {
                "title": "Agent Systems Review",
                "sections": [
                    {"id": "planning", "title": "Planning", "target_words": 500},
                    {"id": "tools", "title": "Tools", "target_words": 500},
                ],
            }
        }

    async def fake_peer_review(**kwargs: Any) -> dict[str, Any]:
        del kwargs
        return {
            "review_report": {
                "overall_score": 88,
                "summary": "Complete and supported.",
                "strengths": ["Evidence"],
                "weaknesses": [],
                "suggestions": [],
            },
            "status": "completed",
        }

    def evidence_plans(**kwargs: Any):
        plans = kwargs["sections"]
        return plans, {
            0: {"selected_paper_ids": ["paper-1"]},
            1: {"selected_paper_ids": ["paper-2"]},
        }

    def section_text(payload: dict[str, Any]) -> str:
        sources = json.loads(payload["available_papers_json"])
        number = int(sources[0]["number"])
        return f"Evidence [{number}] " + ("supported analysis " * 150)

    monkeypatch.setattr(
        "academic_cluster.services.database.get_database", lambda: database
    )
    monkeypatch.setattr(research_team, "run_research", fake_research)
    monkeypatch.setattr(
        embedding_service,
        "get_active_embedding_model",
        lambda: "embedding-test-model",
    )
    monkeypatch.setattr(embedding_service, "ensure_paper_embeddings", fake_embeddings)
    monkeypatch.setattr(
        agent_tools,
        "cluster_and_evaluate_coverage",
        _Tool(
            json.dumps(
                {
                    "coverage_score": 0.9,
                    "clusters": [{"paper_ids": ["paper-1", "paper-2"]}],
                    "suggested_new_queries": [],
                }
            )
        ),
    )
    monkeypatch.setattr(
        agent_tools,
        "extract_knowledge_graph",
        _Tool(json.dumps({"entity_count": 2, "relation_count": 1})),
    )
    monkeypatch.setattr(
        agent_tools,
        "generate_evidence",
        _Tool(
            json.dumps(
                {
                    "evidence_cards": [
                        {"paper_id": "paper-1", "claim": "Planning claim"},
                        {"paper_id": "paper-2", "claim": "Tool claim"},
                    ]
                }
            )
        ),
    )
    monkeypatch.setattr(
        agent_tools,
        "analyze_gaps_from_evidence",
        _Tool(json.dumps({"gaps": [], "status": "complete"})),
    )
    monkeypatch.setattr(writing_team, "run_writing", fake_writing)
    monkeypatch.setattr(
        citation_planner,
        "plan_review_citations",
        lambda *_args, **_kwargs: [],
    )
    monkeypatch.setattr(
        section_evidence_planner, "plan_section_evidence", evidence_plans
    )
    monkeypatch.setattr(agent_tools, "write_section", _Tool(section_text))
    monkeypatch.setattr(peer_review_team, "run_peer_review", fake_peer_review)

    await agent_graph.compile_agent_graph(InMemorySaver(), force=True)
    try:
        state = await agent_graph.run_agent_graph(
            topic="agent systems",
            project_id="project-1",
            execution_id="execution-1",
            target_papers=2,
            target_words=1000,
        )
    finally:
        await agent_graph.reset_agent_graph()

    assert state.status == "completed"
    assert state.research_complete
    assert state.analysis_complete
    assert state.writing_complete
    assert state.peer_review_complete
    assert state.current_phase == "completed"
    assert [reference["paper_id"] for reference in state.final_references] == [
        "paper-1",
        "paper-2",
    ]
    assert database.decisions == [
        "research",
        "analysis",
        "writing",
        "peer_review",
        "finalize",
    ]
    assert database.project_statuses[-1] == "completed"
    assert database.final_snapshots[0]["node_name"] == "final_review_artifact"
    assert database.outlines[0]["active_section_ids"] == ["planning", "tools"]
