"""Fail-open and privacy contracts for optional Langfuse tracing."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from academic_cluster.services import langfuse_observability as module
from academic_cluster.services.langfuse_observability import (
    LangfuseConfig,
    LangfuseObservability,
    sanitize_langfuse_payload,
)


class _FakeObservation:
    def __init__(self, *, fail_update: bool = False) -> None:
        self.updates: list[dict[str, Any]] = []
        self.fail_update = fail_update

    def update(self, **kwargs: Any) -> _FakeObservation:
        self.updates.append(kwargs)
        if self.fail_update:
            raise RuntimeError("telemetry update failed")
        return self


class _FakeManager:
    def __init__(
        self,
        client: _FakeClient,
        observation: _FakeObservation,
        trace_id: str,
        *,
        fail_exit: bool = False,
    ) -> None:
        self.client = client
        self.observation = observation
        self.trace_id = trace_id
        self.fail_exit = fail_exit
        self.entered = False
        self.exit_args: tuple[Any, Any, Any] | None = None
        self._prior_trace_id: str | None = None

    def __enter__(self) -> _FakeObservation:
        self.entered = True
        self._prior_trace_id = self.client.current_trace_id
        self.client.current_trace_id = self.trace_id
        return self.observation

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        self.exit_args = (exc_type, exc, tb)
        self.client.current_trace_id = self._prior_trace_id
        if self.fail_exit:
            raise RuntimeError("telemetry cleanup failed")
        return False


class _FakeClient:
    def __init__(
        self,
        *,
        fail_start: bool = False,
        fail_update: bool = False,
        fail_exit: bool = False,
        fail_flush: bool = False,
        fail_shutdown: bool = False,
    ) -> None:
        self.fail_start = fail_start
        self.fail_update = fail_update
        self.fail_exit = fail_exit
        self.fail_flush = fail_flush
        self.fail_shutdown = fail_shutdown
        self.calls: list[dict[str, Any]] = []
        self.managers: list[_FakeManager] = []
        self.trace_seeds: list[str] = []
        self.current_trace_id: str | None = None
        self.flush_count = 0
        self.shutdown_count = 0

    def create_trace_id(self, *, seed: str) -> str:
        self.trace_seeds.append(seed)
        return sha256(seed.encode()).hexdigest()[:32]

    def get_current_trace_id(self) -> str | None:
        return self.current_trace_id

    def start_as_current_observation(self, **kwargs: Any) -> _FakeManager:
        self.calls.append(kwargs)
        if self.fail_start:
            raise RuntimeError("telemetry start failed")
        trace_id = (kwargs.get("trace_context") or {}).get(
            "trace_id", self.current_trace_id
        )
        assert isinstance(trace_id, str)
        manager = _FakeManager(
            self,
            _FakeObservation(fail_update=self.fail_update),
            trace_id,
            fail_exit=self.fail_exit,
        )
        self.managers.append(manager)
        return manager

    def flush(self) -> None:
        self.flush_count += 1
        if self.fail_flush:
            raise RuntimeError("telemetry flush failed")

    def shutdown(self) -> None:
        self.shutdown_count += 1
        if self.fail_shutdown:
            raise RuntimeError("telemetry shutdown failed")


class _AgentStateLike(BaseModel):
    project_id: str
    execution_id: str
    topic: str
    api_key: str


def _enabled_config(**overrides: Any) -> LangfuseConfig:
    values: dict[str, Any] = {
        "enabled": True,
        "public_key": "pk-lf-test-public",
        "secret_key": "sk-lf-test-secret",
    }
    values.update(overrides)
    return LangfuseConfig(**values)


def test_config_uses_application_langfuse_settings() -> None:
    settings = SimpleNamespace(
        langfuse_enabled=True,
        langfuse_public_key=" public ",
        langfuse_secret_key="".join([" sec", "ret "]),
        langfuse_base_url=" https://langfuse.example ",
        langfuse_tracing_environment=" staging ",
        langfuse_release=" release-42 ",
        langfuse_sample_rate=0.25,
        langfuse_capture_node_io=True,
    )

    config = LangfuseConfig.from_settings(settings)

    assert config.enabled is True
    assert config.public_key == "public"
    assert config.secret_key == "secret"
    assert config.base_url == "https://langfuse.example"
    assert config.tracing_environment == "staging"
    assert config.release == "release-42"
    assert config.sample_rate == 0.25
    assert config.capture_inputs is True
    assert config.capture_outputs is True
    assert "secret" not in repr(config)


def test_enabled_without_keys_is_a_safe_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_import(_name: str) -> Any:
        raise AssertionError("SDK import must not be attempted without credentials")

    monkeypatch.setattr(module.importlib, "import_module", unexpected_import)
    observability = LangfuseObservability(config=LangfuseConfig(enabled=True))
    calls = 0

    def node(value: int) -> int:
        nonlocal calls
        calls += 1
        return value + 1

    wrapped = observability.wrap_node(node, node_name="safe-noop")

    assert wrapped(4) == 5
    assert calls == 1
    assert observability.enabled is False
    observability.flush()
    observability.shutdown()


async def test_missing_sdk_keeps_async_node_operational(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        module.importlib,
        "import_module",
        lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("langfuse")),
    )
    observability = LangfuseObservability(config=_enabled_config())

    async def node(value: int) -> int:
        return value * 2

    assert await observability.wrap_node(node)(6) == 12
    assert observability.enabled is False


def test_nested_execution_and_node_share_trace_with_controlled_capture() -> None:
    client = _FakeClient()
    observability = LangfuseObservability(
        config=_enabled_config(capture_inputs=True, capture_outputs=True),
        client=client,
    )

    def node(state: dict[str, Any]) -> dict[str, Any]:
        return {"result": "ok", "api_key": "sk-sensitive-output"}

    wrapped_node = observability.wrap_node(
        node,
        node_name="research",
        contract_version="contract-v2",
        artifact_version="artifact-v3",
        context_version="context-v4",
        metadata={"owner": "agent", "secret": "hidden"},
    )

    def execution(project_id: str, execution_id: str) -> dict[str, Any]:
        return wrapped_node(
            {
                "project_id": project_id,
                "execution_id": execution_id,
                "authorization": "Bearer abc.def.ghi",
            }
        )

    wrapped_execution = observability.wrap_execution(
        execution,
        contract_version="contract-v2",
        artifact_version="artifact-v3",
        context_version="context-v4",
    )

    output = wrapped_execution("project-1", "execution-1")

    assert output["api_key"] == "sk-sensitive-output"
    assert len(client.calls) == 2
    execution_call, node_call = client.calls
    assert execution_call["as_type"] == "agent"
    assert execution_call["name"] == "agent.execution"
    assert node_call["as_type"] == "span"
    assert node_call["name"] == "agent.node.research"
    assert "trace_context" in execution_call
    assert "trace_context" not in node_call
    metadata = node_call["metadata"]
    assert metadata["project_id"] == "project-1"
    assert metadata["execution_id"] == "execution-1"
    assert metadata["node_name"] == "research"
    assert metadata["contract_version"] == "contract-v2"
    assert metadata["artifact_version"] == "artifact-v3"
    assert metadata["context_version"] == "context-v4"
    assert metadata["attributes"]["secret"] == "[REDACTED]"
    node_input = node_call["input"]
    assert node_input["args"][0]["authorization"] == "[REDACTED]"
    node_update = client.managers[1].observation.updates[0]
    assert node_update["metadata"] == {"status": "succeeded"}
    assert node_update["output"]["api_key"] == "[REDACTED]"
    assert client.trace_seeds == [
        "academic-cluster:execution:execution-1",
        "academic-cluster:execution:execution-1",
    ]


async def test_async_business_error_survives_broken_sdk_cleanup() -> None:
    client = _FakeClient(fail_update=True, fail_exit=True)
    observability = LangfuseObservability(config=_enabled_config(), client=client)

    async def node(*, execution_id: str) -> None:
        del execution_id
        raise ValueError("password=hunter2")

    wrapped = observability.wrap_node(node, node_name="analysis")

    with pytest.raises(ValueError, match="password=hunter2"):
        await wrapped(execution_id="execution-2")

    update = client.managers[0].observation.updates[0]
    assert update["level"] == "ERROR"
    assert update["metadata"] == {
        "status": "failed",
        "error_type": "ValueError",
    }
    assert update["status_message"] == "password=[REDACTED]"
    assert client.managers[0].exit_args is not None
    assert client.managers[0].exit_args[0] is ValueError


async def test_async_cancellation_is_reported_without_becoming_a_failure() -> None:
    client = _FakeClient()
    observability = LangfuseObservability(config=_enabled_config(), client=client)

    async def node(*, execution_id: str) -> None:
        del execution_id
        raise asyncio.CancelledError("cancelled by user")

    with pytest.raises(asyncio.CancelledError, match="cancelled by user"):
        await observability.wrap_node(node)(execution_id="execution-cancelled")

    update = client.managers[0].observation.updates[0]
    assert update["metadata"] == {
        "status": "cancelled",
        "error_type": "CancelledError",
    }
    assert update["level"] == "WARNING"
    assert client.managers[0].exit_args == (None, None, None)


def test_sdk_start_failure_does_not_skip_or_repeat_business_call() -> None:
    client = _FakeClient(fail_start=True)
    observability = LangfuseObservability(config=_enabled_config(), client=client)
    calls = 0

    def node() -> str:
        nonlocal calls
        calls += 1
        return "done"

    assert observability.wrap_node(node)() == "done"
    assert calls == 1
    assert len(client.calls) == 1


async def test_flush_and_shutdown_are_fail_open_and_idempotent() -> None:
    client = _FakeClient(fail_flush=True, fail_shutdown=True)
    observability = LangfuseObservability(config=_enabled_config(), client=client)

    observability.flush()
    await observability.aflush()
    observability.shutdown()
    await observability.ashutdown()

    assert client.flush_count == 2
    assert client.shutdown_count == 1
    assert observability.enabled is False


def test_sdk_constructor_receives_v4_security_and_release_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    client = _FakeClient()

    def client_factory(**kwargs: Any) -> _FakeClient:
        captured.update(kwargs)
        return client

    fake_module = SimpleNamespace(
        Langfuse=client_factory,
        propagate_attributes=lambda **_kwargs: None,
    )
    monkeypatch.setattr(module.importlib, "import_module", lambda _name: fake_module)

    observability = LangfuseObservability(
        config=_enabled_config(
            base_url="https://langfuse.example",
            tracing_environment="test",
            release="sha-123",
            sample_rate=0.4,
        )
    )

    assert observability.enabled is True
    assert captured["tracing_enabled"] is True
    assert captured["base_url"] == "https://langfuse.example"
    assert captured["environment"] == "test"
    assert captured["release"] == "sha-123"
    assert captured["sample_rate"] == 0.4
    assert captured["mask"]({"token": "secret"}) == {"token": "[REDACTED]"}
    assert "secret_key" in captured


def test_installed_v4_sdk_disabled_transport_smoke() -> None:
    from langfuse import Langfuse

    credentials = {
        "public_key": "-".join(["pk", "lf", "local-public"]),
        "secret_key": "-".join(["sk", "lf", "local-secret"]),
    }
    client = Langfuse(**credentials, tracing_enabled=False)
    observability = LangfuseObservability(config=_enabled_config(), client=client)

    def node(*, project_id: str, execution_id: str) -> str:
        del project_id, execution_id
        return "ok"

    try:
        result = observability.wrap_node(node, node_name="sdk-smoke")(
            project_id="project-smoke",
            execution_id="execution-smoke",
        )
        observability.flush()
    finally:
        observability.shutdown()

    assert result == "ok"


def test_payload_sanitizer_is_bounded_recursive_and_json_friendly() -> None:
    recursive: dict[str, Any] = {
        "password": "secret",
        "message": "Authorization: Bearer abc123 and token=xyz",
        "values": [float("nan"), b"abc"],
    }
    recursive["self"] = recursive

    sanitized = sanitize_langfuse_payload(recursive, max_value_chars=128)

    assert sanitized["password"] == "[REDACTED]"
    assert "abc123" not in sanitized["message"]
    assert "xyz" not in sanitized["message"]
    assert sanitized["values"] == ["nan", "<bytes:3 bytes>"]
    assert sanitized["self"] == "<dict:recursive>"


def test_capture_serializes_and_redacts_pydantic_agent_state() -> None:
    client = _FakeClient()
    observability = LangfuseObservability(
        config=_enabled_config(capture_inputs=True),
        client=client,
    )
    state = _AgentStateLike(
        project_id="project-state",
        execution_id="execution-state",
        topic="agents",
        api_key="sk-sensitive-state",
    )

    wrapped = observability.wrap_node(lambda current: current.topic)

    assert wrapped(state) == "agents"
    captured_state = client.calls[0]["input"]["args"][0]
    assert captured_state == {
        "project_id": "project-state",
        "execution_id": "execution-state",
        "topic": "agents",
        "api_key": "[REDACTED]",
    }
