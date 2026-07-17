"""Runtime enforcement and trace summaries for production node contracts."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any

import pytest

from academic_cluster.agents.agent_graph import AgentState
from academic_cluster.agents.node_contracts import (
    NodeContractValidationError,
    build_deterministic_fixture,
)
from academic_cluster.agents.node_runtime import (
    enforce_node_contract,
    trace_agent_execution,
)


class _RecordingObservability:
    def __init__(self) -> None:
        self.config = SimpleNamespace(capture_inputs=False, capture_outputs=False)
        self.node_options: list[dict[str, Any]] = []
        self.execution_options: list[dict[str, Any]] = []
        self.node_trace_outputs: list[dict[str, Any]] = []

    def wrap_node(
        self,
        function: Callable[[AgentState], Awaitable[dict[str, Any]]],
        **options: Any,
    ) -> Callable[[AgentState], Awaitable[dict[str, Any]]]:
        self.node_options.append(options)

        async def wrapped(state: AgentState) -> dict[str, Any]:
            output = await function(state)
            self.node_trace_outputs.append(output)
            return output

        return wrapped

    def wrap_execution(
        self,
        function: Callable[..., Awaitable[Any]],
        **options: Any,
    ) -> Callable[..., Awaitable[Any]]:
        self.execution_options.append(options)
        return function


def _state(node: str) -> AgentState:
    return AgentState.model_validate(build_deterministic_fixture(node).state)


async def test_enforced_node_returns_original_update_and_traces_only_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observability = _RecordingObservability()
    fixture = build_deterministic_fixture("writing")

    monkeypatch.setattr(
        "academic_cluster.agents.node_runtime.get_langfuse_observability",
        lambda: observability,
    )

    @enforce_node_contract("writing")
    async def writing(_state: AgentState) -> dict[str, Any]:
        return fixture.output

    output = await writing(_state("writing"))

    assert output == fixture.output
    assert output["final_review"] == "Fixture review [1]."
    trace_output = observability.node_trace_outputs[0]
    assert "final_review" not in trace_output
    assert trace_output["variant"] == "success"
    assert trace_output["artifact_ref"].endswith("writing.output@1.0.0")
    assert observability.node_options[0]["capture_input"] is False
    assert observability.node_options[0]["capture_output"] is True
    assert observability.node_options[0]["metadata"]["input_schema_digest"].startswith(
        "sha256:"
    )


async def test_explicit_io_capture_forwards_validated_payload_to_langfuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observability = _RecordingObservability()
    observability.config.capture_inputs = True
    observability.config.capture_outputs = True
    fixture = build_deterministic_fixture("finalize")
    monkeypatch.setattr(
        "academic_cluster.agents.node_runtime.get_langfuse_observability",
        lambda: observability,
    )

    @enforce_node_contract("finalize")
    async def finalize(_state: AgentState) -> dict[str, Any]:
        return fixture.output

    assert await finalize(_state("finalize")) == fixture.output
    assert observability.node_options[0]["capture_input"] is True
    assert observability.node_trace_outputs[0] == fixture.output


async def test_enforced_node_rejects_invalid_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observability = _RecordingObservability()
    monkeypatch.setattr(
        "academic_cluster.agents.node_runtime.get_langfuse_observability",
        lambda: observability,
    )

    @enforce_node_contract("finalize")
    async def finalize(_state: AgentState) -> dict[str, Any]:
        return {"current_phase": "completed", "status": "not-declared"}

    with pytest.raises(NodeContractValidationError, match="no unique variant"):
        await finalize(_state("finalize"))


async def test_enforced_node_propagates_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observability = _RecordingObservability()
    monkeypatch.setattr(
        "academic_cluster.agents.node_runtime.get_langfuse_observability",
        lambda: observability,
    )

    @enforce_node_contract("research")
    async def research(_state: AgentState) -> dict[str, Any]:
        raise __import__("asyncio").CancelledError

    with pytest.raises(__import__("asyncio").CancelledError):
        await research(_state("research"))


async def test_execution_trace_is_lazy_and_preserves_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observability = _RecordingObservability()
    monkeypatch.setattr(
        "academic_cluster.agents.node_runtime.get_langfuse_observability",
        lambda: observability,
    )

    @trace_agent_execution
    async def run(*, project_id: str, execution_id: str) -> str:
        return f"{project_id}:{execution_id}"

    assert await run(project_id="project-1", execution_id="execution-1") == (
        "project-1:execution-1"
    )
    assert observability.execution_options[0]["capture_input"] is False
    assert observability.execution_options[0]["capture_output"] is False
    assert observability.execution_options[0]["metadata"]["nodes"] == [
        "supervisor",
        "research",
        "analysis",
        "writing",
        "peer_review",
        "finalize",
    ]
