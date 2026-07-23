"""Deterministic supervisor routing and bounded retry tests."""

import json
from typing import Any

import pytest

from academic_cluster.agents import agent_graph
from academic_cluster.agents.agent_graph import AgentState, decide_next_phase


def _state(**updates: object) -> AgentState:
    base: dict[str, object] = {
        "project_id": "project-1",
        "execution_id": "execution-1",
        "topic": "topic",
    }
    base.update(updates)
    return AgentState.model_validate(base)


def test_new_run_routes_to_research() -> None:
    assert decide_next_phase(_state()) == "research"


def test_research_routes_to_analysis() -> None:
    state = _state(research_complete=True, papers=[{"id": "paper-1"}])

    assert decide_next_phase(state) == "analysis"


def test_completed_analysis_routes_to_writing() -> None:
    state = _state(
        research_complete=True,
        analysis_complete=True,
        papers=[{"id": "paper-1"}],
        evidence_cards=[{"paper_id": "paper-1", "claim": "claim"}],
    )

    assert decide_next_phase(state) == "writing"


def test_empty_json_equivalent_does_not_count_as_analysis() -> None:
    state = _state(research_complete=True, papers=[{"id": "paper-1"}])

    assert state.evidence_cards == []
    assert decide_next_phase(state) == "analysis"


def test_low_coverage_routes_back_to_research_with_bound() -> None:
    state = _state(
        research_complete=True,
        status="needs_more_research",
        research_round=1,
        max_research_rounds=2,
    )

    assert decide_next_phase(state) == "research"


def test_low_coverage_exhaustion_finalizes_as_failure() -> None:
    state = _state(
        research_complete=True,
        status="needs_more_research",
        research_round=2,
        max_research_rounds=2,
    )

    assert decide_next_phase(state) == "finalize"


@pytest.mark.asyncio
async def test_analysis_does_not_retry_without_new_research(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CoverageTool:
        async def ainvoke(self, _inputs: dict[str, Any]) -> str:
            return json.dumps(
                {
                    "coverage_score": 0.25,
                    "suggested_new_queries": ["missing aspect"],
                }
            )

    async def ensure_embeddings(
        papers: list[dict[str, Any]],
        *,
        model_name: str,
    ) -> int:
        assert model_name == "embedding-model"
        return len(papers)

    monkeypatch.setattr(
        "academic_cluster.services.embedding_service.get_active_embedding_model",
        lambda: "embedding-model",
    )
    monkeypatch.setattr(
        "academic_cluster.services.embedding_service.ensure_paper_embeddings",
        ensure_embeddings,
    )
    monkeypatch.setattr(
        "academic_cluster.tools.agent_tools.cluster_and_evaluate_coverage",
        _CoverageTool(),
    )
    state = _state(
        papers=[{"id": f"paper-{index}"} for index in range(3)],
        research_complete=True,
        research_round=2,
        max_research_rounds=2,
    )

    result = await agent_graph._analysis_node(state)

    assert result["status"] == "needs_more_research"
    assert result["suggested_queries"] == ["missing aspect"]
    assert result["failed_phase"] is None


def test_failed_phase_retries_then_stops() -> None:
    retry = _state(
        failed_phase="analysis",
        phase_attempts={"analysis": 1},
        max_phase_attempts=2,
    )
    exhausted = retry.model_copy(
        update={"phase_attempts": {"analysis": 2}, "terminal_failure": True}
    )

    assert decide_next_phase(retry) == "analysis"
    assert decide_next_phase(exhausted) == "finalize"


def test_review_revision_is_bounded() -> None:
    revise = _state(
        research_complete=True,
        analysis_complete=True,
        writing_complete=True,
        status="needs_revision",
        revision_attempt=1,
        max_revision_attempts=2,
    )
    exhausted = revise.model_copy(update={"revision_attempt": 2})

    assert decide_next_phase(revise) == "writing"
    assert decide_next_phase(exhausted) == "finalize"


def test_successful_review_routes_to_finalize() -> None:
    state = _state(
        research_complete=True,
        papers=[{"id": "paper-1"}],
        analysis_complete=True,
        writing_complete=True,
        final_review="review [1]",
        peer_review_complete=True,
    )

    assert decide_next_phase(state) == "finalize"
