"""AgentState contract tests for the production multi-agent graph."""

import json
import math

import pytest
from pydantic import ValidationError

from academic_cluster.agents.agent_graph import AgentState


def test_agent_state_defaults_are_checkpoint_safe() -> None:
    state = AgentState(project_id="project-1", execution_id="execution-1", topic="AI")

    payload = state.model_dump(mode="json")

    assert payload["current_phase"] == "supervisor"
    assert payload["status"] == "created"
    assert payload["papers"] == []
    assert payload["evidence_cards"] == []
    assert payload["phase_attempts"] == {}
    assert json.loads(state.model_dump_json())["execution_id"] == "execution-1"


def test_agent_state_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AgentState(project_id="p", execution_id="e", topic="t", unknown=True)


def test_agent_state_round_trip_preserves_native_structures() -> None:
    state = AgentState(
        project_id="p",
        execution_id="e",
        topic="topic",
        papers=[{"id": "paper-1", "title": "Paper"}],
        evidence_cards=[{"paper_id": "paper-1", "claim": "Claim"}],
        reference_map=[{"number": 1, "paper_id": "paper-1"}],
        phase_attempts={"research": 1},
    )

    restored = AgentState.model_validate_json(state.model_dump_json())

    assert restored == state
    assert restored.papers[0]["id"] == "paper-1"


def test_execution_id_is_not_silently_discarded() -> None:
    state = AgentState(project_id="p", execution_id="run-42", topic="topic")

    assert state.execution_id == "run-42"
    assert state.model_dump()["execution_id"] == "run-42"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_papers", 0),
        ("target_papers", 501),
        ("target_words", 999),
        ("target_words", 100001),
        ("quality_threshold", -1),
        ("quality_threshold", 101),
        ("quality_threshold", math.nan),
        ("quality_threshold", math.inf),
        ("coverage_score", math.nan),
        ("max_research_rounds", 0),
        ("max_research_rounds", 11),
        ("max_revision_attempts", -1),
        ("max_revision_attempts", 11),
        ("max_phase_attempts", 0),
        ("max_phase_attempts", 11),
    ],
)
def test_agent_state_rejects_invalid_control_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        AgentState.model_validate(
            {
                "project_id": "p",
                "execution_id": "e",
                "topic": "t",
                field: value,
            }
        )
