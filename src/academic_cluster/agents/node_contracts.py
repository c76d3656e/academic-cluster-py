"""Versioned runtime contracts for the six production Agent graph nodes.

The contracts in this module are descriptive and independently consumable.
They project the fields actually read and written by ``agent_graph`` without
changing LangGraph state semantics or importing the graph implementation.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CONTRACT_VERSION = "1.0.0"
MANIFEST_VERSION = "1.0.0"

NodeName = Literal[
    "supervisor",
    "research",
    "analysis",
    "writing",
    "peer_review",
    "finalize",
]
ArtifactDirection = Literal["input", "output"]
JsonKind = Literal["string", "integer", "number", "boolean", "object", "array"]

NODE_NAMES: tuple[NodeName, ...] = (
    "supervisor",
    "research",
    "analysis",
    "writing",
    "peer_review",
    "finalize",
)


class _ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ArtifactField(_ContractModel):
    """One JSON-compatible field in a projected node artifact."""

    name: str = Field(min_length=1)
    json_kind: JsonKind
    required: bool = False
    nullable: bool = False


class ArtifactVariant(_ContractModel):
    """Status-selected output requirements for one node branch."""

    name: str = Field(min_length=1)
    statuses: tuple[str, ...] = Field(min_length=1)
    required_fields: tuple[str, ...] = ()
    description: str = ""


class ArtifactContract(_ContractModel):
    """Versioned input or output artifact declaration."""

    artifact_id: str = Field(min_length=1)
    version: str = CONTRACT_VERSION
    node: NodeName
    direction: ArtifactDirection
    fields: tuple[ArtifactField, ...]
    variants: tuple[ArtifactVariant, ...] = ()

    @model_validator(mode="after")
    def validate_declaration(self) -> Self:
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate artifact fields in {self.artifact_id}")
        known = set(names)
        if self.direction == "input" and self.variants:
            raise ValueError("input artifacts cannot declare output variants")
        statuses: set[str] = set()
        for variant in self.variants:
            unknown = set(variant.required_fields) - known
            if unknown:
                raise ValueError(
                    f"variant {variant.name} references unknown fields: "
                    f"{sorted(unknown)}"
                )
            duplicate_statuses = statuses.intersection(variant.statuses)
            if duplicate_statuses:
                raise ValueError(
                    f"output statuses map to multiple variants: "
                    f"{sorted(duplicate_statuses)}"
                )
            statuses.update(variant.statuses)
        return self


class ParameterBinding(_ContractModel):
    """Map AgentState fields to one concrete operation parameter."""

    parameter: str = Field(min_length=1)
    source_fields: tuple[str, ...] = ()
    expression: str = "direct"


class InvocationContract(_ContractModel):
    """One service, tool, or deterministic function called by a node."""

    operation: str = Field(min_length=1)
    bindings: tuple[ParameterBinding, ...] = ()
    required: bool = True
    side_effect: bool = False


class DependencyManifest(_ContractModel):
    """Static execution dependencies and external interactions for a node."""

    phase: str
    context_vars: tuple[str, ...] = ()
    invocations: tuple[InvocationContract, ...] = ()
    side_effects: tuple[str, ...] = ()


class FallbackRule(_ContractModel):
    """A deterministic non-exception or degraded branch."""

    trigger: str
    action: str
    resulting_status: str | None = None
    terminal: bool = False


class DeclaredError(_ContractModel):
    """Machine-readable failure condition and its runtime disposition."""

    code: str = Field(min_length=1)
    condition: str = Field(min_length=1)
    exception_types: tuple[str, ...] = ()
    handling: Literal["propagate", "phase_retry", "fail_closed", "best_effort"]
    retryable: bool
    terminal: bool
    result_status: str | None = None


class ErrorSemantics(_ContractModel):
    """Cancellation, exception, retry, and fallback behavior."""

    cancellation: Literal["propagate"] = "propagate"
    exception_policy: Literal[
        "phase_retry",
        "propagate",
        "best_effort_only",
    ]
    failure_status: str | None = None
    retry_fields: tuple[str, ...] = ()
    declared_errors: tuple[DeclaredError, ...] = Field(min_length=1)
    fallbacks: tuple[FallbackRule, ...] = ()


class AcceptanceCriterion(_ContractModel):
    """Machine-readable condition a contract consumer must demonstrate."""

    criterion_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    check: Literal[
        "input_version",
        "input_required",
        "input_types",
        "output_variant",
        "error_policy",
        "fallback_policy",
    ]
    expected: Any


class NodeContract(_ContractModel):
    """Complete static contract for one production graph node."""

    name: NodeName
    version: str = CONTRACT_VERSION
    input_artifact: ArtifactContract
    output_artifact: ArtifactContract
    context: DependencyManifest
    errors: ErrorSemantics
    acceptance_criteria: tuple[AcceptanceCriterion, ...]

    @model_validator(mode="after")
    def validate_artifacts(self) -> Self:
        if self.input_artifact.node != self.name:
            raise ValueError("input artifact node does not match contract")
        if self.output_artifact.node != self.name:
            raise ValueError("output artifact node does not match contract")
        if self.input_artifact.direction != "input":
            raise ValueError("input_artifact must have input direction")
        if self.output_artifact.direction != "output":
            raise ValueError("output_artifact must have output direction")
        if self.input_artifact.version != self.version:
            raise ValueError("input artifact version does not match contract")
        if self.output_artifact.version != self.version:
            raise ValueError("output artifact version does not match contract")
        required_checks = {
            "input_version",
            "input_required",
            "input_types",
            "output_variant",
            "error_policy",
            "fallback_policy",
        }
        actual_checks = {criterion.check for criterion in self.acceptance_criteria}
        if not required_checks.issubset(actual_checks):
            raise ValueError(
                f"{self.name} acceptance criteria are incomplete: "
                f"{sorted(required_checks - actual_checks)}"
            )
        return self


class VersionedArtifact(_ContractModel):
    """A runtime payload projected and validated against a contract."""

    artifact_id: str
    version: str
    node: NodeName
    direction: ArtifactDirection
    variant: str | None = None
    payload: dict[str, Any]


class NodeManifestEntry(_ContractModel):
    """One contract plus its directly consumable Artifact JSON Schemas."""

    node: NodeName
    contract: NodeContract
    input_artifact_schema: dict[str, Any]
    output_artifact_schema: dict[str, Any]


class NodeContractManifest(_ContractModel):
    """Stable, JSON-serializable registry and Artifact schema manifest."""

    manifest_version: str = MANIFEST_VERSION
    contract_version: str = CONTRACT_VERSION
    nodes: tuple[NodeManifestEntry, ...]


class ContextManifest(_ContractModel):
    """Runtime identity and schema provenance for one node invocation."""

    manifest_version: str = MANIFEST_VERSION
    contract_version: str = CONTRACT_VERSION
    node: NodeName
    project_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    input_artifact_ref: str = Field(min_length=1)
    input_schema_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class InvocationManifest(_ContractModel):
    """Deterministic runtime invocation envelope for acceptance and audit."""

    manifest_version: str = MANIFEST_VERSION
    contract_version: str = CONTRACT_VERSION
    node: NodeName
    project_id: str = Field(min_length=1)
    execution_id: str = Field(min_length=1)
    input_artifact_ref: str = Field(min_length=1)
    input_schema_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    invocation_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    context: ContextManifest
    input_artifact: VersionedArtifact

    @model_validator(mode="after")
    def validate_context_copy(self) -> Self:
        copied = (
            self.manifest_version,
            self.contract_version,
            self.node,
            self.project_id,
            self.execution_id,
            self.input_artifact_ref,
            self.input_schema_digest,
        )
        contextual = (
            self.context.manifest_version,
            self.context.contract_version,
            self.context.node,
            self.context.project_id,
            self.context.execution_id,
            self.context.input_artifact_ref,
            self.context.input_schema_digest,
        )
        if copied != contextual:
            raise ValueError("invocation fields do not match runtime context")
        return self


class NodeAcceptanceFixture(_ContractModel):
    """Deterministic fixture for contract consumers and CI acceptance."""

    fixture_version: str = "1.0.0"
    contract_version: str = CONTRACT_VERSION
    node: NodeName
    scenario: str = "success"
    state: dict[str, Any]
    output: dict[str, Any]
    expected_variant: str


class NodeAcceptanceResult(_ContractModel):
    """Non-throwing acceptance result for one deterministic fixture."""

    node: NodeName
    accepted: bool
    errors: tuple[str, ...] = ()
    evaluated_criteria: tuple[str, ...] = ()
    input_artifact: VersionedArtifact | None = None
    output_artifact: VersionedArtifact | None = None


class NodeContractValidationError(ValueError):
    """Raised when a runtime projection violates a node contract."""


_STATE_FIELD_SHAPES: dict[str, tuple[JsonKind, bool]] = {
    "project_id": ("string", False),
    "execution_id": ("string", False),
    "topic": ("string", False),
    "target_papers": ("integer", False),
    "target_words": ("integer", False),
    "quality_threshold": ("number", False),
    "current_phase": ("string", False),
    "status": ("string", False),
    "decision_reason": ("string", False),
    "papers": ("array", False),
    "paper_ids": ("array", False),
    "research_summary": ("object", False),
    "research_complete": ("boolean", False),
    "research_round": ("integer", False),
    "max_research_rounds": ("integer", False),
    "suggested_queries": ("array", False),
    "embeddings_ready": ("boolean", False),
    "embedding_model": ("string", False),
    "coverage": ("object", False),
    "coverage_score": ("number", False),
    "knowledge_graph": ("object", False),
    "evidence_cards": ("array", False),
    "gap_analysis": ("object", False),
    "analysis_complete": ("boolean", False),
    "outline": ("object", False),
    "sections": ("array", False),
    "reference_map": ("array", False),
    "cited_reference_numbers": ("array", False),
    "final_references": ("array", False),
    "abstract": ("string", False),
    "final_review": ("string", False),
    "writing_complete": ("boolean", False),
    "peer_review_report": ("object", False),
    "quality_score": ("number", True),
    "peer_review_complete": ("boolean", False),
    "needs_revision": ("boolean", False),
    "revision_feedback": ("string", False),
    "revision_attempt": ("integer", False),
    "max_revision_attempts": ("integer", False),
    "phase_attempts": ("object", False),
    "max_phase_attempts": ("integer", False),
    "failed_phase": ("string", True),
    "terminal_failure": ("boolean", False),
    "warnings": ("array", False),
    "errors": ("array", False),
}


def _artifact_fields(
    names: tuple[str, ...],
    *,
    required: tuple[str, ...],
) -> tuple[ArtifactField, ...]:
    unknown = set(names) - _STATE_FIELD_SHAPES.keys()
    if unknown:
        raise ValueError(f"unknown AgentState fields in contract: {sorted(unknown)}")
    required_names = set(required)
    if not required_names.issubset(names):
        raise ValueError("required artifact fields are not declared")
    return tuple(
        ArtifactField(
            name=name,
            json_kind=_STATE_FIELD_SHAPES[name][0],
            nullable=_STATE_FIELD_SHAPES[name][1],
            required=name in required_names,
        )
        for name in names
    )


def _artifact(
    node: NodeName,
    direction: ArtifactDirection,
    names: tuple[str, ...],
    *,
    required: tuple[str, ...],
    variants: tuple[ArtifactVariant, ...] = (),
) -> ArtifactContract:
    return ArtifactContract(
        artifact_id=f"academic-cluster.agent.{node}.{direction}",
        node=node,
        direction=direction,
        fields=_artifact_fields(names, required=required),
        variants=variants,
    )


def _binding(
    parameter: str,
    *source_fields: str,
    expression: str = "direct",
) -> ParameterBinding:
    return ParameterBinding(
        parameter=parameter,
        source_fields=tuple(source_fields),
        expression=expression,
    )


def _variant(
    name: str,
    status: str,
    *required_fields: str,
    description: str,
) -> ArtifactVariant:
    return ArtifactVariant(
        name=name,
        statuses=(status,),
        required_fields=tuple(required_fields),
        description=description,
    )


def _contract_violation_error() -> DeclaredError:
    return DeclaredError(
        code="contract_violation",
        condition="Input or output Artifact violates its versioned schema.",
        exception_types=("NodeContractValidationError",),
        handling="fail_closed",
        retryable=False,
        terminal=True,
        result_status="failed",
    )


def _cancelled_error() -> DeclaredError:
    return DeclaredError(
        code="cancelled",
        condition="The asyncio task is cancelled by the runtime.",
        exception_types=("asyncio.CancelledError",),
        handling="propagate",
        retryable=False,
        terminal=False,
        result_status="interrupted",
    )


def _phase_retry_errors(
    phase: str,
    *fallbacks: FallbackRule,
) -> ErrorSemantics:
    return ErrorSemantics(
        exception_policy="phase_retry",
        failure_status=f"{phase}_failed",
        retry_fields=("phase_attempts", "max_phase_attempts"),
        declared_errors=(
            _contract_violation_error(),
            _cancelled_error(),
            DeclaredError(
                code="phase_execution_error",
                condition=(
                    f"{phase} raises before producing a valid success or fallback output."
                ),
                exception_types=("Exception",),
                handling="phase_retry",
                retryable=True,
                terminal=False,
                result_status=f"{phase}_failed",
            ),
            DeclaredError(
                code="phase_retry_exhausted",
                condition="phase_attempts reaches max_phase_attempts.",
                handling="phase_retry",
                retryable=False,
                terminal=True,
                result_status=f"{phase}_failed",
            ),
        ),
        fallbacks=tuple(fallbacks),
    )


def _acceptance_criteria(
    node: NodeName,
    input_fields: tuple[str, ...],
    output_variants: tuple[str, ...],
    error_policy: str,
) -> tuple[AcceptanceCriterion, ...]:
    return (
        AcceptanceCriterion(
            criterion_id=f"{node}.input.version",
            description="Input Artifact version matches the node contract.",
            check="input_version",
            expected=CONTRACT_VERSION,
        ),
        AcceptanceCriterion(
            criterion_id=f"{node}.input.required",
            description="Every AgentState field read by the node is present.",
            check="input_required",
            expected=list(input_fields),
        ),
        AcceptanceCriterion(
            criterion_id=f"{node}.input.types",
            description="Projected values match their finite JSON runtime types.",
            check="input_types",
            expected={name: _STATE_FIELD_SHAPES[name][0] for name in input_fields},
        ),
        AcceptanceCriterion(
            criterion_id=f"{node}.output.variant",
            description="Output status selects one declared branch variant.",
            check="output_variant",
            expected=list(output_variants),
        ),
        AcceptanceCriterion(
            criterion_id=f"{node}.error.policy",
            description="Cancellation and exceptions follow the declared policy.",
            check="error_policy",
            expected={"cancellation": "propagate", "exception_policy": error_policy},
        ),
        AcceptanceCriterion(
            criterion_id=f"{node}.fallback.policy",
            description="At least one explicit fallback or degraded branch is declared.",
            check="fallback_policy",
            expected={"minimum_rules": 1},
        ),
    )


_SUPERVISOR_INPUT = (
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
)
_SUPERVISOR_OUTPUT = (
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
)

_RESEARCH_INPUT = (
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
)
_RESEARCH_OUTPUT = (
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
)

_ANALYSIS_INPUT = (
    "project_id",
    "execution_id",
    "topic",
    "target_papers",
    "papers",
    "warnings",
    "phase_attempts",
    "max_phase_attempts",
    "errors",
)
_ANALYSIS_OUTPUT = (
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
)

_WRITING_INPUT = (
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
)
_WRITING_OUTPUT = (
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
)

_PEER_REVIEW_INPUT = (
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
)
_PEER_REVIEW_OUTPUT = (
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
)

_FINALIZE_INPUT = (
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
)
_FINALIZE_OUTPUT = ("current_phase", "status")


NODE_CONTRACTS: dict[NodeName, NodeContract] = {
    "supervisor": NodeContract(
        name="supervisor",
        input_artifact=_artifact(
            "supervisor",
            "input",
            _SUPERVISOR_INPUT,
            required=_SUPERVISOR_INPUT,
        ),
        output_artifact=_artifact(
            "supervisor",
            "output",
            _SUPERVISOR_OUTPUT,
            required=("current_phase", "status", "decision_reason"),
            variants=(
                _variant(
                    "route",
                    "running",
                    description="Route or bounded retry remains runnable.",
                ),
                _variant(
                    "finalize",
                    "finalizing",
                    description="All required phases are complete.",
                ),
                _variant(
                    "terminal_failure",
                    "failed",
                    "terminal_failure",
                    description="Coverage or phase retry budget is exhausted.",
                ),
                _variant(
                    "revision_exhausted",
                    "completed_with_warnings",
                    "needs_revision",
                    "warnings",
                    description="Revision budget is exhausted; preserve the review.",
                ),
            ),
        ),
        context=DependencyManifest(
            phase="supervisor",
            invocations=(
                InvocationContract(
                    operation="decide_next_phase",
                    bindings=(
                        _binding("state", *_SUPERVISOR_INPUT, expression="AgentState"),
                    ),
                ),
                InvocationContract(
                    operation="database.record_agent_decision",
                    bindings=(
                        _binding("execution_id", "execution_id"),
                        _binding("project_id", "project_id"),
                        _binding("decision", expression="decide_next_phase(state)"),
                        _binding("reason", expression="computed branch reason"),
                    ),
                    required=False,
                    side_effect=True,
                ),
            ),
            side_effects=("best-effort supervisor decision audit",),
        ),
        errors=ErrorSemantics(
            exception_policy="best_effort_only",
            declared_errors=(
                _contract_violation_error(),
                _cancelled_error(),
                DeclaredError(
                    code="decision_audit_persistence_error",
                    condition="record_agent_decision raises an Exception.",
                    exception_types=("Exception",),
                    handling="best_effort",
                    retryable=False,
                    terminal=False,
                    result_status=None,
                ),
            ),
            fallbacks=(
                FallbackRule(
                    trigger="decision audit persistence fails",
                    action="log warning and keep routing result",
                ),
                FallbackRule(
                    trigger="coverage retry budget exhausted",
                    action="mark terminal failure",
                    resulting_status="failed",
                    terminal=True,
                ),
                FallbackRule(
                    trigger="revision budget exhausted",
                    action="preserve review and append warning",
                    resulting_status="completed_with_warnings",
                    terminal=True,
                ),
            ),
        ),
        acceptance_criteria=_acceptance_criteria(
            "supervisor",
            _SUPERVISOR_INPUT,
            ("route", "finalize", "terminal_failure", "revision_exhausted"),
            "best_effort_only",
        ),
    ),
    "research": NodeContract(
        name="research",
        input_artifact=_artifact(
            "research", "input", _RESEARCH_INPUT, required=_RESEARCH_INPUT
        ),
        output_artifact=_artifact(
            "research",
            "output",
            _RESEARCH_OUTPUT,
            required=("current_phase", "status", "failed_phase", "terminal_failure"),
            variants=(
                _variant(
                    "success",
                    "running",
                    "papers",
                    "paper_ids",
                    "research_summary",
                    "research_complete",
                    "research_round",
                    "suggested_queries",
                    description="Project-scoped papers were returned and deduplicated.",
                ),
                _variant(
                    "phase_failure",
                    "research_failed",
                    "phase_attempts",
                    "errors",
                    "warnings",
                    description="Failure is converted to the bounded phase retry state.",
                ),
            ),
        ),
        context=DependencyManifest(
            phase="research",
            context_vars=("project_id", "execution_id", "agent_phase"),
            invocations=(
                InvocationContract(
                    operation="research_team.run_research",
                    bindings=(
                        _binding("topic", "topic"),
                        _binding("project_id", "project_id"),
                        _binding("target_papers", "target_papers"),
                        _binding("supplemental_queries", "suggested_queries"),
                    ),
                ),
            ),
            side_effects=(
                "paper persistence and project linking through research tools",
            ),
        ),
        errors=_phase_retry_errors(
            "research",
            FallbackRule(
                trigger="research returns no project papers",
                action="raise and enter bounded phase retry",
                resulting_status="research_failed",
            ),
        ),
        acceptance_criteria=_acceptance_criteria(
            "research",
            _RESEARCH_INPUT,
            ("success", "phase_failure"),
            "phase_retry",
        ),
    ),
    "analysis": NodeContract(
        name="analysis",
        input_artifact=_artifact(
            "analysis", "input", _ANALYSIS_INPUT, required=_ANALYSIS_INPUT
        ),
        output_artifact=_artifact(
            "analysis",
            "output",
            _ANALYSIS_OUTPUT,
            required=(
                "current_phase",
                "status",
                "failed_phase",
                "terminal_failure",
                "warnings",
            ),
            variants=(
                _variant(
                    "supplemental_research",
                    "needs_more_research",
                    "embeddings_ready",
                    "embedding_model",
                    "coverage",
                    "coverage_score",
                    "suggested_queries",
                    "analysis_complete",
                    description="Coverage below 0.55 requests bounded supplemental research.",
                ),
                _variant(
                    "success",
                    "running",
                    "embeddings_ready",
                    "embedding_model",
                    "coverage",
                    "coverage_score",
                    "knowledge_graph",
                    "evidence_cards",
                    "gap_analysis",
                    "analysis_complete",
                    description="Coverage and real evidence are sufficient for writing.",
                ),
                _variant(
                    "phase_failure",
                    "analysis_failed",
                    "phase_attempts",
                    "errors",
                    description="Required analysis failed and entered bounded retry.",
                ),
            ),
        ),
        context=DependencyManifest(
            phase="analysis",
            context_vars=("project_id", "execution_id", "agent_phase"),
            invocations=(
                InvocationContract(
                    operation="embedding_service.get_active_embedding_model",
                ),
                InvocationContract(
                    operation="embedding_service.ensure_paper_embeddings",
                    bindings=(
                        _binding("papers", "papers"),
                        _binding(
                            "model_name",
                            expression="get_active_embedding_model()",
                        ),
                    ),
                ),
                InvocationContract(
                    operation="agent_tools.cluster_and_evaluate_coverage",
                    bindings=(
                        _binding("topic", "topic"),
                        _binding("target_papers", "target_papers"),
                        _binding(
                            "embedding_model",
                            expression="active model",
                        ),
                    ),
                ),
                InvocationContract(
                    operation="agent_tools.extract_knowledge_graph",
                    bindings=(
                        _binding("papers_json", "papers", expression="bounded JSON"),
                    ),
                    required=False,
                ),
                InvocationContract(
                    operation="agent_tools.generate_evidence",
                    bindings=(
                        _binding("papers_json", "papers", expression="bounded JSON"),
                        _binding("topic", "topic"),
                    ),
                ),
                InvocationContract(
                    operation="agent_tools.analyze_gaps_from_evidence",
                    bindings=(
                        _binding(
                            "evidence_count",
                            "evidence_cards",
                            expression="len(generated cards)",
                        ),
                        _binding(
                            "key_claims_json",
                            "evidence_cards",
                            expression="first 20 claims JSON",
                        ),
                        _binding("topic", "topic"),
                    ),
                    required=False,
                ),
            ),
            side_effects=(
                "embedding persistence",
                "cluster persistence",
                "knowledge graph persistence",
                "evidence card persistence",
            ),
        ),
        errors=_phase_retry_errors(
            "analysis",
            FallbackRule(
                trigger="coverage score below 0.55",
                action="request suggested queries or the original topic",
                resulting_status="needs_more_research",
            ),
            FallbackRule(
                trigger="knowledge graph extraction errors or truncation",
                action="append warning and continue with evidence",
                resulting_status="running",
            ),
            FallbackRule(
                trigger="gap analysis reports an error",
                action="append warning and retain degraded gap artifact",
                resulting_status="running",
            ),
            FallbackRule(
                trigger="no real evidence cards remain",
                action="raise and enter bounded phase retry",
                resulting_status="analysis_failed",
            ),
        ),
        acceptance_criteria=_acceptance_criteria(
            "analysis",
            _ANALYSIS_INPUT,
            ("supplemental_research", "success", "phase_failure"),
            "phase_retry",
        ),
    ),
    "writing": NodeContract(
        name="writing",
        input_artifact=_artifact(
            "writing", "input", _WRITING_INPUT, required=_WRITING_INPUT
        ),
        output_artifact=_artifact(
            "writing",
            "output",
            _WRITING_OUTPUT,
            required=("current_phase", "status", "failed_phase", "terminal_failure"),
            variants=(
                _variant(
                    "success",
                    "running",
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
                    description="Grounded sections and final markdown passed validation.",
                ),
                _variant(
                    "phase_failure",
                    "writing_failed",
                    "phase_attempts",
                    "errors",
                    "warnings",
                    description="Writing or artifact persistence entered bounded retry.",
                ),
            ),
        ),
        context=DependencyManifest(
            phase="writing",
            context_vars=("project_id", "execution_id", "agent_phase"),
            invocations=(
                InvocationContract(
                    operation="writing_team.run_writing",
                    bindings=(
                        _binding("topic", "topic"),
                        _binding("evidence_cards", "evidence_cards"),
                        _binding("target_words", "target_words"),
                    ),
                    required=False,
                ),
                InvocationContract(
                    operation="citation_planner.plan_review_citations",
                    bindings=(
                        _binding("sections", "outline"),
                        _binding("papers", "papers", "reference_map"),
                        _binding("clusters", "coverage"),
                    ),
                    required=False,
                ),
                InvocationContract(
                    operation="section_evidence_planner.plan_section_evidence",
                    bindings=(
                        _binding("topic", "topic"),
                        _binding("evidence_cards", "evidence_cards"),
                        _binding("papers", "papers"),
                        _binding("clusters", "coverage"),
                    ),
                    required=False,
                ),
                InvocationContract(
                    operation="agent_tools.write_section",
                    bindings=(
                        _binding("topic", "topic"),
                        _binding("section_plan_json", "outline"),
                        _binding(
                            "available_papers_json",
                            "papers",
                            "reference_map",
                            "evidence_cards",
                        ),
                    ),
                    required=False,
                ),
                InvocationContract(
                    operation="agent_tools.revise_section",
                    bindings=(
                        _binding("section_text", "sections", "final_references"),
                        _binding("revision_instructions", "revision_feedback"),
                    ),
                    required=False,
                ),
                InvocationContract(
                    operation="review_finalizer.finalize_review_markdown",
                    bindings=(
                        _binding("review_title", "outline", "topic"),
                        _binding("sections", "outline"),
                        _binding("section_bodies", "sections"),
                        _binding("paper_metadata_map", "reference_map"),
                        _binding("abstract", "sections", expression="computed"),
                    ),
                ),
                InvocationContract(
                    operation="database.save_outline",
                    bindings=(
                        _binding("project_id", "project_id"),
                        _binding("outline", "outline"),
                        _binding("revision_attempt", "revision_attempt"),
                    ),
                    side_effect=True,
                ),
                InvocationContract(
                    operation="database.save_written_section",
                    bindings=(
                        _binding("sections", "sections"),
                        _binding("revision_attempt", "revision_attempt"),
                        _binding("quality_score", "quality_score"),
                    ),
                    side_effect=True,
                ),
            ),
            side_effects=("outline and written section persistence",),
        ),
        errors=_phase_retry_errors(
            "writing",
            FallbackRule(
                trigger="needs_revision is true",
                action="revise existing sections and restore original citation numbers",
                resulting_status="running",
            ),
            FallbackRule(
                trigger="citation, evidence-plan, or minimum-length validation fails",
                action="raise and enter bounded phase retry",
                resulting_status="writing_failed",
            ),
        ),
        acceptance_criteria=_acceptance_criteria(
            "writing",
            _WRITING_INPUT,
            ("success", "phase_failure"),
            "phase_retry",
        ),
    ),
    "peer_review": NodeContract(
        name="peer_review",
        input_artifact=_artifact(
            "peer_review",
            "input",
            _PEER_REVIEW_INPUT,
            required=_PEER_REVIEW_INPUT,
        ),
        output_artifact=_artifact(
            "peer_review",
            "output",
            _PEER_REVIEW_OUTPUT,
            required=("current_phase", "status", "failed_phase"),
            variants=(
                _variant(
                    "revision_requested",
                    "needs_revision",
                    "peer_review_report",
                    "quality_score",
                    "peer_review_complete",
                    "needs_revision",
                    "revision_feedback",
                    description="Score is below threshold and revisions remain.",
                ),
                _variant(
                    "threshold_warning",
                    "completed_with_warnings",
                    "peer_review_report",
                    "quality_score",
                    "peer_review_complete",
                    "needs_revision",
                    "warnings",
                    description="Score remains low after the revision budget.",
                ),
                _variant(
                    "success",
                    "running",
                    "peer_review_report",
                    "quality_score",
                    "peer_review_complete",
                    "needs_revision",
                    "terminal_failure",
                    description="Validated score meets the quality threshold.",
                ),
                _variant(
                    "phase_failure",
                    "peer_review_failed",
                    "terminal_failure",
                    "phase_attempts",
                    "errors",
                    "warnings",
                    description="Missing text or invalid review entered bounded retry.",
                ),
            ),
        ),
        context=DependencyManifest(
            phase="peer_review",
            context_vars=("project_id", "execution_id", "agent_phase"),
            invocations=(
                InvocationContract(
                    operation="peer_review_team.run_peer_review",
                    bindings=(
                        _binding("review_text", "final_review"),
                        _binding("topic", "topic"),
                    ),
                ),
                InvocationContract(
                    operation="peer_review_team.validate_peer_review_report",
                    bindings=(_binding("report", expression="run_peer_review result"),),
                ),
            ),
        ),
        errors=_phase_retry_errors(
            "peer_review",
            FallbackRule(
                trigger="score below threshold with revisions remaining",
                action="store feedback and route back to writing",
                resulting_status="needs_revision",
            ),
            FallbackRule(
                trigger="score below threshold after revision budget",
                action="complete with warning and preserve review",
                resulting_status="completed_with_warnings",
                terminal=True,
            ),
        ),
        acceptance_criteria=_acceptance_criteria(
            "peer_review",
            _PEER_REVIEW_INPUT,
            (
                "revision_requested",
                "threshold_warning",
                "success",
                "phase_failure",
            ),
            "phase_retry",
        ),
    ),
    "finalize": NodeContract(
        name="finalize",
        input_artifact=_artifact(
            "finalize", "input", _FINALIZE_INPUT, required=_FINALIZE_INPUT
        ),
        output_artifact=_artifact(
            "finalize",
            "output",
            _FINALIZE_OUTPUT,
            required=_FINALIZE_OUTPUT,
            variants=(
                _variant(
                    "success",
                    "completed",
                    description="Review completed without warnings.",
                ),
                _variant(
                    "warning",
                    "completed_with_warnings",
                    description="Review completed while preserving warnings.",
                ),
                _variant(
                    "failure",
                    "failed",
                    description="Terminal failure or missing final review.",
                ),
            ),
        ),
        context=DependencyManifest(
            phase="finalize",
            invocations=(
                InvocationContract(
                    operation="database.save_pipeline_checkpoint",
                    bindings=(
                        _binding("project_id", "project_id"),
                        _binding(
                            "state_snapshot",
                            "final_review",
                            "final_references",
                            "abstract",
                            "outline",
                            "peer_review_report",
                            "quality_score",
                            "coverage",
                            "warnings",
                        ),
                        _binding(
                            "status",
                            "terminal_failure",
                            "final_review",
                            "status",
                            "warnings",
                            expression="derived final status",
                        ),
                    ),
                    required=False,
                    side_effect=True,
                ),
            ),
            side_effects=("final_review_artifact checkpoint persistence",),
        ),
        errors=ErrorSemantics(
            exception_policy="propagate",
            declared_errors=(
                _contract_violation_error(),
                _cancelled_error(),
                DeclaredError(
                    code="finalize_persistence_error",
                    condition=(
                        "save_pipeline_checkpoint raises while final_review is present."
                    ),
                    exception_types=("Exception",),
                    handling="propagate",
                    retryable=False,
                    terminal=True,
                    result_status="failed",
                ),
            ),
            fallbacks=(
                FallbackRule(
                    trigger="terminal_failure is true or final_review is empty",
                    action="return failed and skip artifact persistence when text is empty",
                    resulting_status="failed",
                    terminal=True,
                ),
                FallbackRule(
                    trigger="state has warnings or completed_with_warnings status",
                    action="preserve warnings in the final artifact",
                    resulting_status="completed_with_warnings",
                    terminal=True,
                ),
            ),
        ),
        acceptance_criteria=_acceptance_criteria(
            "finalize",
            _FINALIZE_INPUT,
            ("success", "warning", "failure"),
            "propagate",
        ),
    ),
}


def get_node_contract(node: str) -> NodeContract:
    """Return one registered contract or raise a stable validation error."""

    try:
        return NODE_CONTRACTS[node]  # type: ignore[index]
    except KeyError as error:
        raise NodeContractValidationError(f"unknown Agent node: {node}") from error


def _runtime_mapping(value: Mapping[str, Any] | BaseModel) -> dict[str, Any]:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="python")
    if isinstance(value, Mapping):
        return dict(value)
    raise NodeContractValidationError("runtime artifact source must be a mapping")


def _matches_json_kind(value: Any, kind: JsonKind) -> bool:
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
        )
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "object":
        return isinstance(value, Mapping)
    return isinstance(value, list)


def _validate_payload(
    artifact: ArtifactContract,
    payload: dict[str, Any],
    *,
    reject_unknown: bool,
) -> str | None:
    fields = {field.name: field for field in artifact.fields}
    if reject_unknown:
        unknown = set(payload) - fields.keys()
        if unknown:
            raise NodeContractValidationError(
                f"{artifact.node} {artifact.direction} has unknown fields: "
                f"{sorted(unknown)}"
            )
    missing = [
        field.name
        for field in artifact.fields
        if field.required and field.name not in payload
    ]
    if missing:
        raise NodeContractValidationError(
            f"{artifact.node} {artifact.direction} is missing fields: {missing}"
        )
    for name, value in payload.items():
        field = fields.get(name)
        if field is None:
            continue
        if value is None and field.nullable:
            continue
        if value is None or not _matches_json_kind(value, field.json_kind):
            raise NodeContractValidationError(
                f"{artifact.node} {artifact.direction}.{name} must be "
                f"{field.json_kind}{' or null' if field.nullable else ''}"
            )

    if artifact.direction == "input":
        return None
    status = payload.get("status")
    matching = [variant for variant in artifact.variants if status in variant.statuses]
    if len(matching) != 1:
        raise NodeContractValidationError(
            f"{artifact.node} output status {status!r} has no unique variant"
        )
    variant = matching[0]
    variant_missing = [name for name in variant.required_fields if name not in payload]
    if variant_missing:
        raise NodeContractValidationError(
            f"{artifact.node} output variant {variant.name} is missing fields: "
            f"{variant_missing}"
        )
    return variant.name


def project_node_input(
    node: str,
    state: Mapping[str, Any] | BaseModel,
) -> VersionedArtifact:
    """Project and validate only the AgentState fields a node actually reads."""

    contract = get_node_contract(node)
    source = _runtime_mapping(state)
    payload = {
        field.name: source[field.name]
        for field in contract.input_artifact.fields
        if field.name in source
    }
    _validate_payload(contract.input_artifact, payload, reject_unknown=False)
    return VersionedArtifact(
        artifact_id=contract.input_artifact.artifact_id,
        version=contract.input_artifact.version,
        node=contract.name,
        direction="input",
        payload=payload,
    )


def validate_node_output(
    node: str,
    output: Mapping[str, Any] | BaseModel,
) -> VersionedArtifact:
    """Validate a node update and return its versioned output artifact."""

    contract = get_node_contract(node)
    payload = _runtime_mapping(output)
    variant = _validate_payload(
        contract.output_artifact,
        payload,
        reject_unknown=True,
    )
    return VersionedArtifact(
        artifact_id=contract.output_artifact.artifact_id,
        version=contract.output_artifact.version,
        node=contract.name,
        direction="output",
        variant=variant,
        payload=payload,
    )


def build_artifact_json_schema(artifact: ArtifactContract) -> dict[str, Any]:
    """Build a Draft 2020-12 schema for one concrete Artifact version."""

    properties: dict[str, Any] = {}
    for field in artifact.fields:
        field_type: str | list[str]
        field_type = [field.json_kind, "null"] if field.nullable else field.json_kind
        properties[field.name] = {"type": field_type}

    common_required = [field.name for field in artifact.fields if field.required]
    schema: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": (
            f"urn:academic-cluster:agent-artifact:{artifact.node}:"
            f"{artifact.direction}:{artifact.version}"
        ),
        "title": artifact.artifact_id,
        "type": "object",
        "x-artifact-id": artifact.artifact_id,
        "x-artifact-version": artifact.version,
        "x-node": artifact.node,
        "x-direction": artifact.direction,
        "properties": properties,
        "required": common_required,
        "additionalProperties": False,
    }
    if artifact.direction == "output":
        schema["oneOf"] = [
            {
                "title": variant.name,
                "properties": {"status": {"enum": list(variant.statuses)}},
                "required": list(dict.fromkeys(("status", *variant.required_fields))),
            }
            for variant in artifact.variants
        ]
        schema["allOf"] = [
            {
                "if": {
                    "properties": {"status": {"enum": list(variant.statuses)}},
                    "required": ["status"],
                },
                "then": {
                    "required": list(
                        dict.fromkeys((*common_required, *variant.required_fields))
                    )
                },
            }
            for variant in artifact.variants
        ]
    return schema


def export_artifact_json_schemas() -> dict[str, dict[str, Any]]:
    """Export every input/output Artifact schema by stable versioned reference."""

    result: dict[str, dict[str, Any]] = {}
    for node in NODE_NAMES:
        contract = NODE_CONTRACTS[node]
        for artifact in (contract.input_artifact, contract.output_artifact):
            reference = f"{artifact.artifact_id}@{artifact.version}"
            result[reference] = build_artifact_json_schema(artifact)
    return result


def _schema_digest(artifact: ArtifactContract) -> str:
    canonical = json.dumps(
        build_artifact_json_schema(artifact),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def build_context_manifest(
    node: str,
    state: Mapping[str, Any] | BaseModel,
) -> ContextManifest:
    """Build runtime identity and input-schema provenance for an invocation."""

    contract = get_node_contract(node)
    source = _runtime_mapping(state)
    project_id = source.get("project_id")
    execution_id = source.get("execution_id")
    if not isinstance(project_id, str) or not project_id:
        raise NodeContractValidationError("runtime context requires project_id")
    if not isinstance(execution_id, str) or not execution_id:
        raise NodeContractValidationError("runtime context requires execution_id")
    artifact = contract.input_artifact
    return ContextManifest(
        node=contract.name,
        project_id=project_id,
        execution_id=execution_id,
        input_artifact_ref=f"{artifact.artifact_id}@{artifact.version}",
        input_schema_digest=_schema_digest(artifact),
    )


def build_invocation_manifest(
    node: str,
    state: Mapping[str, Any] | BaseModel,
) -> InvocationManifest:
    """Build one deterministic runtime invocation manifest and input Artifact."""

    input_artifact = project_node_input(node, state)
    context = build_context_manifest(node, state)
    canonical = json.dumps(
        {
            "context": context.model_dump(mode="json"),
            "input_artifact": input_artifact.model_dump(mode="json"),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return InvocationManifest(
        node=context.node,
        project_id=context.project_id,
        execution_id=context.execution_id,
        input_artifact_ref=context.input_artifact_ref,
        input_schema_digest=context.input_schema_digest,
        invocation_id=f"sha256:{hashlib.sha256(canonical).hexdigest()}",
        context=context,
        input_artifact=input_artifact,
    )


def export_contract_manifest() -> dict[str, Any]:
    """Export the registry as a deterministic JSON-compatible manifest."""

    manifest = NodeContractManifest(
        nodes=tuple(
            NodeManifestEntry(
                node=name,
                contract=NODE_CONTRACTS[name],
                input_artifact_schema=build_artifact_json_schema(
                    NODE_CONTRACTS[name].input_artifact
                ),
                output_artifact_schema=build_artifact_json_schema(
                    NODE_CONTRACTS[name].output_artifact
                ),
            )
            for name in NODE_NAMES
        )
    )
    return manifest.model_dump(mode="json")


def export_contract_manifest_json(*, indent: int | None = 2) -> str:
    """Export the deterministic manifest as JSON text."""

    return json.dumps(
        export_contract_manifest(),
        ensure_ascii=False,
        indent=indent,
        sort_keys=True,
    )


def export_contract_json_schema() -> dict[str, Any]:
    """Export the Pydantic JSON Schema for contract manifest consumers."""

    return NodeContractManifest.model_json_schema()


def _base_state_fixture() -> dict[str, Any]:
    return {
        "project_id": "project-fixture",
        "execution_id": "execution-fixture",
        "topic": "deterministic agent fixture",
        "target_papers": 10,
        "target_words": 3000,
        "quality_threshold": 75.0,
        "current_phase": "supervisor",
        "status": "created",
        "decision_reason": "",
        "papers": [{"id": "paper-1", "title": "Agent systems"}],
        "paper_ids": ["paper-1"],
        "research_summary": {},
        "research_complete": False,
        "research_round": 0,
        "max_research_rounds": 2,
        "suggested_queries": [],
        "embeddings_ready": False,
        "embedding_model": "embedding-fixture",
        "coverage": {"coverage_score": 0.8, "clusters": []},
        "coverage_score": 0.8,
        "knowledge_graph": {},
        "evidence_cards": [{"paper_id": "paper-1", "claim": "Fixture evidence"}],
        "gap_analysis": {},
        "analysis_complete": False,
        "outline": {"title": "Fixture review", "sections": []},
        "sections": [{"section_id": "1", "content": "Evidence [1]."}],
        "reference_map": [{"number": 1, "paper_id": "paper-1"}],
        "cited_reference_numbers": [1],
        "final_references": [
            {"original_number": 1, "new_number": 1, "paper_id": "paper-1"}
        ],
        "abstract": "Fixture abstract [1].",
        "final_review": "Fixture review [1].",
        "writing_complete": False,
        "peer_review_report": {"overall_score": 88.0},
        "quality_score": 88.0,
        "peer_review_complete": False,
        "needs_revision": False,
        "revision_feedback": "",
        "revision_attempt": 0,
        "max_revision_attempts": 2,
        "phase_attempts": {},
        "max_phase_attempts": 2,
        "failed_phase": None,
        "terminal_failure": False,
        "warnings": [],
        "errors": [],
    }


_SUCCESS_OUTPUT_FIXTURES: dict[NodeName, tuple[str, dict[str, Any]]] = {
    "supervisor": (
        "route",
        {
            "current_phase": "research",
            "status": "running",
            "decision_reason": "phase completion state",
        },
    ),
    "research": (
        "success",
        {
            "current_phase": "research",
            "status": "running",
            "papers": [{"id": "paper-1"}],
            "paper_ids": ["paper-1"],
            "research_summary": {"total_found": 1},
            "research_complete": True,
            "research_round": 1,
            "suggested_queries": [],
            "failed_phase": None,
            "terminal_failure": False,
        },
    ),
    "analysis": (
        "success",
        {
            "current_phase": "analysis",
            "status": "running",
            "embeddings_ready": True,
            "embedding_model": "embedding-fixture",
            "coverage": {"coverage_score": 0.8},
            "coverage_score": 0.8,
            "knowledge_graph": {},
            "evidence_cards": [{"paper_id": "paper-1", "claim": "Fixture evidence"}],
            "gap_analysis": {},
            "analysis_complete": True,
            "failed_phase": None,
            "terminal_failure": False,
            "warnings": [],
        },
    ),
    "writing": (
        "success",
        {
            "current_phase": "writing",
            "status": "running",
            "outline": {"title": "Fixture review"},
            "sections": [{"section_id": "1", "content": "Evidence [1]."}],
            "reference_map": [{"number": 1, "paper_id": "paper-1"}],
            "cited_reference_numbers": [1],
            "final_references": [
                {"original_number": 1, "new_number": 1, "paper_id": "paper-1"}
            ],
            "abstract": "Fixture abstract [1].",
            "final_review": "Fixture review [1].",
            "writing_complete": True,
            "needs_revision": False,
            "revision_feedback": "",
            "peer_review_complete": False,
            "revision_attempt": 0,
            "failed_phase": None,
            "terminal_failure": False,
        },
    ),
    "peer_review": (
        "success",
        {
            "current_phase": "peer_review",
            "status": "running",
            "peer_review_report": {"overall_score": 88.0},
            "quality_score": 88.0,
            "peer_review_complete": True,
            "needs_revision": False,
            "failed_phase": None,
            "terminal_failure": False,
        },
    ),
    "finalize": (
        "success",
        {"current_phase": "completed", "status": "completed"},
    ),
}


def build_deterministic_fixture(node: str) -> NodeAcceptanceFixture:
    """Build one stable happy-path fixture for a registered node."""

    contract = get_node_contract(node)
    expected_variant, output = _SUCCESS_OUTPUT_FIXTURES[contract.name]
    return NodeAcceptanceFixture(
        node=contract.name,
        state=_base_state_fixture(),
        output=output,
        expected_variant=expected_variant,
    )


def build_all_deterministic_fixtures() -> tuple[NodeAcceptanceFixture, ...]:
    """Build fixtures in graph order for CI and downstream consumers."""

    return tuple(build_deterministic_fixture(name) for name in NODE_NAMES)


def accept_node_fixture(fixture: NodeAcceptanceFixture) -> NodeAcceptanceResult:
    """Evaluate a fixture without throwing, returning stable acceptance details."""

    if fixture.contract_version != CONTRACT_VERSION:
        return NodeAcceptanceResult(
            node=fixture.node,
            accepted=False,
            errors=(
                f"fixture contract version {fixture.contract_version} does not match "
                f"{CONTRACT_VERSION}",
            ),
        )
    try:
        contract = get_node_contract(fixture.node)
        if not contract.errors.declared_errors:
            raise NodeContractValidationError("declared errors are required")
        if not contract.errors.fallbacks:
            raise NodeContractValidationError("fallback rules are required")
        input_artifact = project_node_input(fixture.node, fixture.state)
        output_artifact = validate_node_output(fixture.node, fixture.output)
        if output_artifact.variant != fixture.expected_variant:
            raise NodeContractValidationError(
                f"expected variant {fixture.expected_variant}, got "
                f"{output_artifact.variant}"
            )
    except (NodeContractValidationError, ValueError, TypeError) as error:
        return NodeAcceptanceResult(
            node=fixture.node,
            accepted=False,
            errors=(str(error),),
        )
    return NodeAcceptanceResult(
        node=fixture.node,
        accepted=True,
        evaluated_criteria=tuple(
            criterion.criterion_id for criterion in contract.acceptance_criteria
        ),
        input_artifact=input_artifact,
        output_artifact=output_artifact,
    )
