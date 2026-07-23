"""The runtime facade must preserve the complete terminal Agent state."""

from __future__ import annotations

from typing import Any

import pytest

from academic_cluster.agents import agent_graph, orchestrator


@pytest.mark.asyncio
async def test_orchestrator_forwards_execution_contract_and_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []
    state = agent_graph.AgentState(
        project_id="project-1",
        execution_id="execution-1",
        topic="agent safety",
        status="completed_with_warnings",
        current_phase="completed",
        papers=[{"id": "paper-1"}],
        coverage={"coverage_score": 0.9},
        knowledge_graph={"entity_count": 1},
        evidence_cards=[{"paper_id": "paper-1", "claim": "claim"}],
        outline={"title": "Survey"},
        sections=[{"title": "Body", "content": "Evidence [1]."}],
        final_references=[{"number": 1, "paper_id": "paper-1"}],
        abstract="Abstract [1].",
        final_review="Review [1].",
        peer_review_report={"overall_score": 88},
        quality_score=88,
        warnings=["warning"],
    )

    async def run_graph(**kwargs: Any) -> agent_graph.AgentState:
        calls.append(kwargs)
        return state

    monkeypatch.setattr(agent_graph, "run_agent_graph", run_graph)
    facade = orchestrator.create_orchestrator(
        model_name="ignored-project-model",
        quality_threshold=87.5,
    )

    result = await facade.run(
        topic="agent safety",
        project_id="project-1",
        execution_id="execution-1",
        target_papers=25,
        target_words=5000,
        resume=True,
        sse_manager="sse",
    )

    assert calls == [
        {
            "topic": "agent safety",
            "project_id": "project-1",
            "execution_id": "execution-1",
            "target_papers": 25,
            "target_words": 5000,
            "quality_threshold": 87.5,
            "resume": True,
            "sse_manager": "sse",
        }
    ]
    assert result == {
        "project_id": "project-1",
        "execution_id": "execution-1",
        "topic": "agent safety",
        "status": "completed_with_warnings",
        "current_phase": "completed",
        "papers": [{"id": "paper-1"}],
        "coverage": {"coverage_score": 0.9},
        "knowledge_graph": {"entity_count": 1},
        "evidence_cards": [{"paper_id": "paper-1", "claim": "claim"}],
        "outline": {"title": "Survey"},
        "sections": [{"title": "Body", "content": "Evidence [1]."}],
        "references": [{"number": 1, "paper_id": "paper-1"}],
        "abstract": "Abstract [1].",
        "final_review": "Review [1].",
        "peer_review": {"overall_score": 88},
        "quality_score": 88.0,
        "warnings": ["warning"],
        "errors": [],
    }
