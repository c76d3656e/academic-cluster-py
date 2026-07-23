"""Executable contracts for every production Agent graph node."""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from academic_cluster.agents.agent_graph import AgentState
from academic_cluster.agents.node_contracts import (
    CONTRACT_VERSION,
    NODE_CONTRACTS,
    NODE_NAMES,
    NodeAcceptanceFixture,
    NodeContractValidationError,
    accept_node_fixture,
    build_all_deterministic_fixtures,
    build_artifact_json_schema,
    build_context_manifest,
    build_deterministic_fixture,
    build_invocation_manifest,
    export_artifact_json_schemas,
    export_contract_json_schema,
    export_contract_manifest,
    export_contract_manifest_json,
    get_node_contract,
    project_node_input,
    validate_node_output,
)

EXPECTED_INPUT_FIELDS: dict[str, set[str]] = {
    "supervisor": {
        "project_id",
        "execution_id",
        "status",
        "terminal_failure",
        "failed_phase",
        "phase_attempts",
        "max_phase_attempts",
        "research_round",
        "max_research_rounds",
        "needs_revision",
        "revision_attempt",
        "max_revision_attempts",
        "research_complete",
        "papers",
        "analysis_complete",
        "writing_complete",
        "final_review",
        "peer_review_complete",
        "errors",
        "warnings",
    },
    "research": {
        "project_id",
        "execution_id",
        "topic",
        "target_papers",
        "suggested_queries",
        "research_round",
        "phase_attempts",
        "max_phase_attempts",
        "errors",
        "warnings",
    },
    "analysis": {
        "project_id",
        "execution_id",
        "topic",
        "target_papers",
        "papers",
        "warnings",
        "phase_attempts",
        "max_phase_attempts",
        "errors",
    },
    "writing": {
        "project_id",
        "execution_id",
        "topic",
        "target_words",
        "papers",
        "evidence_cards",
        "coverage",
        "reference_map",
        "needs_revision",
        "outline",
        "sections",
        "final_references",
        "revision_feedback",
        "revision_attempt",
        "quality_score",
        "phase_attempts",
        "max_phase_attempts",
        "errors",
        "warnings",
    },
    "peer_review": {
        "project_id",
        "execution_id",
        "topic",
        "final_review",
        "quality_threshold",
        "revision_attempt",
        "max_revision_attempts",
        "warnings",
        "phase_attempts",
        "max_phase_attempts",
        "errors",
    },
    "finalize": {
        "project_id",
        "terminal_failure",
        "final_review",
        "status",
        "warnings",
        "final_references",
        "abstract",
        "outline",
        "peer_review_report",
        "quality_score",
        "coverage",
    },
}

EXPECTED_OUTPUT_FIELDS: dict[str, set[str]] = {
    "supervisor": {
        "current_phase",
        "status",
        "decision_reason",
        "research_complete",
        "analysis_complete",
        "embeddings_ready",
        "terminal_failure",
        "errors",
        "failed_phase",
        "writing_complete",
        "peer_review_complete",
        "needs_revision",
        "warnings",
    },
    "research": {
        "current_phase",
        "status",
        "papers",
        "paper_ids",
        "research_summary",
        "research_complete",
        "research_round",
        "suggested_queries",
        "failed_phase",
        "terminal_failure",
        "phase_attempts",
        "errors",
        "warnings",
    },
    "analysis": {
        "current_phase",
        "status",
        "embeddings_ready",
        "embedding_model",
        "coverage",
        "coverage_score",
        "suggested_queries",
        "analysis_complete",
        "failed_phase",
        "terminal_failure",
        "warnings",
        "knowledge_graph",
        "evidence_cards",
        "gap_analysis",
        "phase_attempts",
        "errors",
    },
    "writing": {
        "current_phase",
        "status",
        "outline",
        "sections",
        "reference_map",
        "cited_reference_numbers",
        "final_references",
        "abstract",
        "final_review",
        "writing_complete",
        "needs_revision",
        "revision_feedback",
        "peer_review_complete",
        "revision_attempt",
        "failed_phase",
        "terminal_failure",
        "phase_attempts",
        "errors",
        "warnings",
    },
    "peer_review": {
        "current_phase",
        "status",
        "peer_review_report",
        "quality_score",
        "peer_review_complete",
        "needs_revision",
        "revision_feedback",
        "failed_phase",
        "terminal_failure",
        "warnings",
        "phase_attempts",
        "errors",
    },
    "finalize": {"current_phase", "status"},
}


EXPECTED_OPERATIONS: dict[str, tuple[str, ...]] = {
    "supervisor": (
        "decide_next_phase",
        "database.record_agent_decision",
    ),
    "research": ("research_team.run_research",),
    "analysis": (
        "embedding_service.get_active_embedding_model",
        "embedding_service.ensure_paper_embeddings",
        "agent_tools.cluster_and_evaluate_coverage",
        "agent_tools.extract_knowledge_graph",
        "agent_tools.generate_evidence",
        "agent_tools.analyze_gaps_from_evidence",
    ),
    "writing": (
        "writing_team.run_writing",
        "citation_planner.plan_review_citations",
        "section_evidence_planner.plan_section_evidence",
        "agent_tools.write_section",
        "agent_tools.revise_section",
        "review_finalizer.finalize_review_markdown",
        "database.save_outline",
        "database.save_written_section",
    ),
    "peer_review": (
        "peer_review_team.run_peer_review",
        "peer_review_team.validate_peer_review_report",
    ),
    "finalize": ("database.save_pipeline_checkpoint",),
}


def _field_names(fields: tuple[Any, ...]) -> set[str]:
    return {str(field.name) for field in fields}


def test_registry_covers_only_the_six_production_nodes() -> None:
    assert tuple(NODE_CONTRACTS) == NODE_NAMES
    assert set(NODE_CONTRACTS) == {
        "supervisor",
        "research",
        "analysis",
        "writing",
        "peer_review",
        "finalize",
    }
    assert all(
        contract.version == CONTRACT_VERSION for contract in NODE_CONTRACTS.values()
    )


@pytest.mark.parametrize("node", NODE_NAMES)
def test_contract_field_projection_matches_audited_agent_graph(node: str) -> None:
    contract = get_node_contract(node)

    assert _field_names(contract.input_artifact.fields) == EXPECTED_INPUT_FIELDS[node]
    assert _field_names(contract.output_artifact.fields) == EXPECTED_OUTPUT_FIELDS[node]
    assert contract.input_artifact.direction == "input"
    assert contract.output_artifact.direction == "output"
    assert contract.input_artifact.version == CONTRACT_VERSION
    assert contract.output_artifact.version == CONTRACT_VERSION


@pytest.mark.parametrize("node", NODE_NAMES)
def test_context_manifest_matches_actual_node_invocations(node: str) -> None:
    contract = get_node_contract(node)

    assert (
        tuple(call.operation for call in contract.context.invocations)
        == (EXPECTED_OPERATIONS[node])
    )
    if node in {"research", "analysis", "writing", "peer_review"}:
        assert contract.context.context_vars == (
            "project_id",
            "execution_id",
            "agent_phase",
        )
    else:
        assert contract.context.context_vars == ()


def test_phase_error_and_fallback_semantics_are_explicit() -> None:
    for phase in ("research", "analysis", "writing", "peer_review"):
        errors = get_node_contract(phase).errors
        assert errors.cancellation == "propagate"
        assert errors.exception_policy == "phase_retry"
        assert errors.failure_status == f"{phase}_failed"
        assert errors.retry_fields == ("phase_attempts", "max_phase_attempts")
        assert errors.fallbacks
        error_codes = {error.code for error in errors.declared_errors}
        assert error_codes >= {
            "contract_violation",
            "cancelled",
            "phase_execution_error",
            "phase_retry_exhausted",
        }

    supervisor = get_node_contract("supervisor").errors
    assert supervisor.exception_policy == "best_effort_only"
    assert {error.code for error in supervisor.declared_errors} >= {
        "contract_violation",
        "cancelled",
        "decision_audit_persistence_error",
    }
    assert {rule.resulting_status for rule in supervisor.fallbacks} >= {
        "failed",
        "completed_with_warnings",
    }

    finalize = get_node_contract("finalize").errors
    assert finalize.exception_policy == "propagate"
    assert {error.code for error in finalize.declared_errors} >= {
        "contract_violation",
        "cancelled",
        "finalize_persistence_error",
    }
    assert {rule.resulting_status for rule in finalize.fallbacks} == {
        "failed",
        "completed_with_warnings",
    }


@pytest.mark.parametrize("node", NODE_NAMES)
def test_each_node_has_structured_acceptance_criteria(node: str) -> None:
    criteria = get_node_contract(node).acceptance_criteria

    assert {criterion.check for criterion in criteria} == {
        "input_version",
        "input_required",
        "input_types",
        "output_variant",
        "error_policy",
        "fallback_policy",
    }
    assert len({criterion.criterion_id for criterion in criteria}) == len(criteria)
    assert all(criterion.description for criterion in criteria)
    assert all(criterion.expected is not None for criterion in criteria)


def test_manifest_and_json_schema_exports_are_stable_and_round_trip() -> None:
    manifest = export_contract_manifest()
    manifest_text = export_contract_manifest_json(indent=None)
    schema = export_contract_json_schema()

    assert json.loads(manifest_text) == manifest
    assert manifest["manifest_version"] == "1.0.0"
    assert manifest["contract_version"] == CONTRACT_VERSION
    assert [node["node"] for node in manifest["nodes"]] == list(NODE_NAMES)
    assert all("input_artifact_schema" in node for node in manifest["nodes"])
    assert all("output_artifact_schema" in node for node in manifest["nodes"])
    assert schema["type"] == "object"
    assert "NodeContract" in schema["$defs"]
    assert "ArtifactContract" in schema["$defs"]
    assert export_contract_manifest_json(indent=None) == manifest_text


@pytest.mark.parametrize("node", NODE_NAMES)
def test_real_artifact_json_schemas_are_closed_and_versioned(node: str) -> None:
    contract = get_node_contract(node)
    schemas = export_artifact_json_schemas()
    input_ref = (
        f"{contract.input_artifact.artifact_id}@{contract.input_artifact.version}"
    )
    output_ref = (
        f"{contract.output_artifact.artifact_id}@{contract.output_artifact.version}"
    )
    input_schema = schemas[input_ref]
    output_schema = schemas[output_ref]

    assert input_schema == build_artifact_json_schema(contract.input_artifact)
    assert input_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert input_schema["x-artifact-id"] == contract.input_artifact.artifact_id
    assert input_schema["x-artifact-version"] == CONTRACT_VERSION
    assert input_schema["additionalProperties"] is False
    assert set(input_schema["required"]) == EXPECTED_INPUT_FIELDS[node]
    assert set(input_schema["properties"]) == EXPECTED_INPUT_FIELDS[node]

    assert output_schema["$schema"] == input_schema["$schema"]
    assert output_schema["additionalProperties"] is False
    assert set(output_schema["properties"]) == EXPECTED_OUTPUT_FIELDS[node]
    assert len(output_schema["oneOf"]) == len(contract.output_artifact.variants)
    assert len(output_schema["allOf"]) == len(contract.output_artifact.variants)
    assert all("if" in branch and "then" in branch for branch in output_schema["allOf"])


def test_runtime_context_and_invocation_manifest_are_deterministic() -> None:
    state = AgentState(
        project_id="project-1",
        execution_id="execution-1",
        topic="agent contracts",
    )

    context = build_context_manifest("research", state)
    first = build_invocation_manifest("research", state)
    second = build_invocation_manifest("research", state)

    assert context.manifest_version == "1.0.0"
    assert context.contract_version == CONTRACT_VERSION
    assert context.node == "research"
    assert context.project_id == "project-1"
    assert context.execution_id == "execution-1"
    assert context.input_artifact_ref.endswith(f"@{CONTRACT_VERSION}")
    assert context.input_schema_digest.startswith("sha256:")
    assert len(context.input_schema_digest) == len("sha256:") + 64
    assert first.context == context
    assert first.manifest_version == context.manifest_version
    assert first.contract_version == context.contract_version
    assert first.node == context.node
    assert first.project_id == context.project_id
    assert first.execution_id == context.execution_id
    assert first.input_artifact_ref == context.input_artifact_ref
    assert first.input_schema_digest == context.input_schema_digest
    assert first.input_artifact.direction == "input"
    assert first.invocation_id == second.invocation_id


def test_runtime_context_requires_execution_identity_even_for_finalize() -> None:
    fixture = build_deterministic_fixture("finalize")
    missing_execution = dict(fixture.state)
    missing_execution.pop("execution_id")

    with pytest.raises(NodeContractValidationError, match="execution_id"):
        build_context_manifest("finalize", missing_execution)


def test_input_projection_accepts_agent_state_and_drops_unread_fields() -> None:
    state = AgentState(
        project_id="project-1",
        execution_id="execution-1",
        topic="agent contracts",
    )

    artifact = project_node_input("research", state)

    assert artifact.node == "research"
    assert artifact.direction == "input"
    assert artifact.version == CONTRACT_VERSION
    assert set(artifact.payload) == EXPECTED_INPUT_FIELDS["research"]
    assert "current_phase" not in artifact.payload
    assert json.loads(artifact.model_dump_json())["payload"]["topic"] == (
        "agent contracts"
    )


def test_input_projection_rejects_missing_or_wrongly_typed_fields() -> None:
    fixture = build_deterministic_fixture("analysis")
    missing = dict(fixture.state)
    missing.pop("papers")
    wrong_type = {**fixture.state, "target_papers": True}

    with pytest.raises(NodeContractValidationError, match="missing fields"):
        project_node_input("analysis", missing)
    with pytest.raises(
        NodeContractValidationError, match="target_papers must be integer"
    ):
        project_node_input("analysis", wrong_type)
    with pytest.raises(NodeContractValidationError, match="unknown Agent node"):
        project_node_input("unknown", fixture.state)


@pytest.mark.parametrize("node", NODE_NAMES)
def test_deterministic_success_outputs_validate_the_expected_variant(node: str) -> None:
    fixture = build_deterministic_fixture(node)

    artifact = validate_node_output(node, fixture.output)

    assert artifact.node == node
    assert artifact.direction == "output"
    assert artifact.variant == fixture.expected_variant


@pytest.mark.parametrize(
    ("node", "output", "variant"),
    [
        (
            "research",
            {
                "current_phase": "research",
                "status": "research_failed",
                "failed_phase": "research",
                "terminal_failure": False,
                "phase_attempts": {"research": 1},
                "errors": [],
                "warnings": ["retrying"],
            },
            "phase_failure",
        ),
        (
            "analysis",
            {
                "current_phase": "analysis",
                "status": "needs_more_research",
                "embeddings_ready": True,
                "embedding_model": "embedding-v1",
                "coverage": {"coverage_score": 0.4},
                "coverage_score": 0.4,
                "suggested_queries": ["missing topic"],
                "analysis_complete": False,
                "failed_phase": None,
                "terminal_failure": False,
                "warnings": [],
            },
            "supplemental_research",
        ),
        (
            "peer_review",
            {
                "current_phase": "peer_review",
                "status": "needs_revision",
                "peer_review_report": {"overall_score": 60},
                "quality_score": 60,
                "peer_review_complete": False,
                "needs_revision": True,
                "revision_feedback": "strengthen evidence",
                "failed_phase": None,
            },
            "revision_requested",
        ),
        (
            "finalize",
            {"current_phase": "completed", "status": "failed"},
            "failure",
        ),
    ],
)
def test_runtime_output_validation_accepts_non_success_branches(
    node: str,
    output: dict[str, Any],
    variant: str,
) -> None:
    assert validate_node_output(node, output).variant == variant


def test_runtime_output_validation_rejects_unknown_missing_and_invalid_values() -> None:
    research = build_deterministic_fixture("research")
    unknown = {**research.output, "undeclared": True}
    missing = dict(research.output)
    missing.pop("papers")
    peer = build_deterministic_fixture("peer_review")
    nonfinite = {**peer.output, "quality_score": math.nan}

    with pytest.raises(NodeContractValidationError, match="unknown fields"):
        validate_node_output("research", unknown)
    with pytest.raises(NodeContractValidationError, match="variant success is missing"):
        validate_node_output("research", missing)
    with pytest.raises(
        NodeContractValidationError, match="quality_score must be number"
    ):
        validate_node_output("peer_review", nonfinite)
    with pytest.raises(NodeContractValidationError, match="has no unique variant"):
        validate_node_output(
            "finalize",
            {"current_phase": "completed", "status": "unexpected"},
        )


def test_all_deterministic_fixtures_pass_acceptance() -> None:
    fixtures = build_all_deterministic_fixtures()
    results = [accept_node_fixture(fixture) for fixture in fixtures]

    assert [fixture.node for fixture in fixtures] == list(NODE_NAMES)
    assert all(result.accepted for result in results)
    assert all(result.input_artifact is not None for result in results)
    assert all(result.output_artifact is not None for result in results)


def test_acceptance_api_returns_stable_rejection_instead_of_throwing() -> None:
    fixture = build_deterministic_fixture("writing")
    bad_output = dict(fixture.output)
    bad_output.pop("final_review")
    rejected = accept_node_fixture(fixture.model_copy(update={"output": bad_output}))
    wrong_version = accept_node_fixture(
        NodeAcceptanceFixture(
            contract_version="2.0.0",
            node="finalize",
            state=build_deterministic_fixture("finalize").state,
            output={"current_phase": "completed", "status": "completed"},
            expected_variant="success",
        )
    )

    assert not rejected.accepted
    assert "variant success is missing" in rejected.errors[0]
    assert not wrong_version.accepted
    assert "does not match" in wrong_version.errors[0]
