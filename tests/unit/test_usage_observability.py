import asyncio
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from academic_cluster.api.admin.providers import get_provider_pricing
from academic_cluster.api.console.usage import get_usage_calls, get_usage_trend
from academic_cluster.services.concurrency import (
    BoundedFifoGate,
    ConcurrencyQueueFullError,
)
from academic_cluster.services.llm_client import (
    AuditedChatModel,
    ainvoke_with_callbacks,
)
from academic_cluster.services.observability import (
    pop_current_agent_phase,
    pop_current_execution,
    pop_current_project,
    push_current_agent_phase,
    push_current_execution,
    push_current_project,
)


class _FakeResponse:
    content = "ok"
    usage_metadata: ClassVar[dict[str, int]] = {"input_tokens": 11, "output_tokens": 7}
    response_metadata: ClassVar[dict[str, str]] = {"model_name": "test-model"}


class _FakeLlm:
    _provider_alias = "test-provider"
    _requested_model = "test-model"
    _upstream_model = "test-model"

    async def ainvoke(self, input, config=None, **kwargs):
        return _FakeResponse()


class _FakeDb:
    def __init__(self):
        self.created_calls = []
        self.finished_calls = []

    async def create_llm_call(self, **kwargs):
        self.created_calls.append(kwargs)
        return "call-1"

    async def finish_llm_call(self, **kwargs):
        self.finished_calls.append(kwargs)


class _FailingLlm:
    _provider_alias = "test-provider"

    async def ainvoke(self, input, config=None, **kwargs):
        raise RuntimeError("boom")


async def test_ainvoke_persists_execution_scoped_llm_call(monkeypatch):
    db = _FakeDb()

    def fake_get_database():
        return db

    async def fake_get_provider_pricing(db, provider_alias, model_name):
        return (0.2, 0.4)

    monkeypatch.setattr(
        "academic_cluster.services.database.get_database", fake_get_database
    )
    monkeypatch.setattr(
        "academic_cluster.api.admin.providers.get_provider_pricing",
        fake_get_provider_pricing,
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client._get_llm_request_gate",
        lambda: (BoundedFifoGate(capacity=1, max_waiters=1), 1.0),
    )

    project_token = push_current_project("project-1")
    execution_token = push_current_execution("execution-1")
    phase_token = push_current_agent_phase("research")
    try:
        await ainvoke_with_callbacks(_FakeLlm(), "hello")
    finally:
        pop_current_agent_phase(phase_token)
        pop_current_execution(execution_token)
        pop_current_project(project_token)

    assert db.created_calls
    assert db.created_calls[0]["pipeline_run_id"] is None
    assert db.created_calls[0]["execution_id"] == "execution-1"
    assert db.created_calls[0]["node_execution_id"] is None
    assert db.created_calls[0]["provider_name"] == "test-provider"
    assert db.created_calls[0]["project_id"] == "project-1"
    assert db.created_calls[0]["node_name"] == "research"
    assert db.created_calls[0]["requested_model"] == "test-model"
    assert db.created_calls[0]["upstream_model"] == "test-model"
    assert db.created_calls[0]["status"] == "running"
    assert db.finished_calls[0]["prompt_tokens"] == 11
    assert db.finished_calls[0]["completion_tokens"] == 7
    assert db.finished_calls[0]["cost"] == 0.000005
    assert db.finished_calls[0]["input_price_per_m"] == 0.2
    assert db.finished_calls[0]["output_price_per_m"] == 0.4


async def test_agent_llm_call_uses_execution_and_task_local_phase(monkeypatch):
    db = _FakeDb()

    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client._get_llm_request_gate",
        lambda: (BoundedFifoGate(capacity=1, max_waiters=1), 1.0),
    )

    project_token = push_current_project("project-agent")
    execution_token = push_current_execution("execution-agent")
    phase_token = push_current_agent_phase("writing")
    try:
        await ainvoke_with_callbacks(_FakeLlm(), "write section")
    finally:
        pop_current_agent_phase(phase_token)
        pop_current_execution(execution_token)
        pop_current_project(project_token)

    assert len(db.created_calls) == 1
    created = db.created_calls[0]
    assert created["project_id"] == "project-agent"
    assert created["execution_id"] == "execution-agent"
    assert created["pipeline_run_id"] is None
    assert created["node_execution_id"] is None
    assert created["node_name"] == "writing"
    assert created["request_metadata"]["agent_phase"] == "writing"


async def test_audited_chat_model_preserves_async_execution_audit(monkeypatch):
    from langchain_core.messages import AIMessage

    class _MessageLlm:
        async def ainvoke(self, input, config=None, **kwargs):
            del input, config, kwargs
            return AIMessage(
                content="audited",
                usage_metadata={
                    "input_tokens": 2,
                    "output_tokens": 1,
                    "total_tokens": 3,
                },
                response_metadata={"model_name": "message-model"},
            )

    db = _FakeDb()
    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client._get_llm_request_gate",
        lambda: (BoundedFifoGate(capacity=1, max_waiters=1), 1.0),
    )

    project_token = push_current_project("project-agent")
    execution_token = push_current_execution("execution-agent")
    phase_token = push_current_agent_phase("research")
    try:
        response = await AuditedChatModel(inner=_MessageLlm()).ainvoke(
            [HumanMessage(content="find papers")]
        )
    finally:
        pop_current_agent_phase(phase_token)
        pop_current_execution(execution_token)
        pop_current_project(project_token)

    assert response.content == "audited"
    assert db.created_calls[0]["execution_id"] == "execution-agent"
    assert db.created_calls[0]["node_name"] == "research"


async def test_bound_tools_reach_router_and_return_structured_tool_calls(monkeypatch):
    from litellm import ModelResponse, Usage

    db = _FakeDb()
    captured: dict[str, Any] = {}
    tool_schema = {
        "type": "function",
        "function": {
            "name": "search_papers",
            "description": "Search papers",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    class _Router:
        async def acompletion(self, **kwargs: Any) -> ModelResponse:
            captured.update(kwargs)
            response = ModelResponse(
                choices=[
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "search_papers",
                                        "arguments": '{"query":"agents"}',
                                    },
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                usage=Usage(
                    prompt_tokens=3,
                    completion_tokens=2,
                    total_tokens=5,
                ),
                model="router-model",
            )
            captured["response_types"] = [
                type(response).__name__,
                type(response.choices[0]).__name__,
                type(response.choices[0].message).__name__,
                type(response.usage).__name__,
            ]
            return response

    bound_model = ChatOpenAI(
        model="fallback-model",
        api_key="test-key",
        base_url="https://provider.invalid/v1",
    ).bind_tools([tool_schema])
    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.services.provider_pool.get_llm_pool",
        lambda: SimpleNamespace(router=_Router()),
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client._get_llm_request_gate",
        lambda: (BoundedFifoGate(capacity=1, max_waiters=1), 1.0),
    )

    project_token = push_current_project("project-agent")
    execution_token = push_current_execution("execution-agent")
    phase_token = push_current_agent_phase("research")
    try:
        response = await ainvoke_with_callbacks(
            bound_model,
            [HumanMessage(content="find papers")],
        )
    finally:
        pop_current_agent_phase(phase_token)
        pop_current_execution(execution_token)
        pop_current_project(project_token)

    assert captured["tools"] == [tool_schema]
    assert captured["response_types"] == [
        "ModelResponse",
        "Choices",
        "Message",
        "Usage",
    ]
    assert response.tool_calls == [
        {
            "name": "search_papers",
            "args": {"query": "agents"},
            "id": "call-1",
            "type": "tool_call",
        }
    ]


async def test_router_response_resolves_the_actual_deployment_alias(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from academic_cluster.services.provider_pool import LiteLLMPool

    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    db = _FakeDb()
    pricing_calls: list[tuple[str, str]] = []
    pool = LiteLLMPool(
        "llm",
        [
            {
                "model_name": "shared-group",
                "litellm_params": {
                    "model": "openai/preferred-model",
                    "api_key": "preferred-key",
                    "api_base": "https://preferred.invalid/v1",
                    "mock_response": "preferred response",
                    "order": -200,
                },
                "model_info": {"provider_alias": "preferred"},
            },
            {
                "model_name": "shared-group",
                "litellm_params": {
                    "model": "openai/fallback-model",
                    "api_key": "fallback-key",
                    "api_base": "https://fallback.invalid/v1",
                    "mock_response": "fallback response",
                    "order": -100,
                },
                "model_info": {"provider_alias": "fallback"},
            },
        ],
    )
    candidate_model = SimpleNamespace(
        _litellm_model="shared-group",
        _provider_alias="fallback",
        _requested_model="fallback-model",
        _upstream_model="fallback-model",
        _api_base_url="https://fallback.invalid/v1",
        api_key="fallback-key",
    )

    async def fake_get_provider_pricing(
        db: Any, provider_alias: str, model_name: str
    ) -> tuple[float, float]:
        del db
        pricing_calls.append((provider_alias, model_name))
        return (0.0, 0.0)

    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: db,
    )
    monkeypatch.setattr(
        "academic_cluster.services.provider_pool.get_llm_pool",
        lambda: pool,
    )
    monkeypatch.setattr(
        "academic_cluster.api.admin.providers.get_provider_pricing",
        fake_get_provider_pricing,
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client._get_llm_request_gate",
        lambda: (BoundedFifoGate(capacity=1, max_waiters=1), 1.0),
    )

    project_token = push_current_project("project-agent")
    execution_token = push_current_execution("execution-agent")
    phase_token = push_current_agent_phase("research")
    try:
        response = await ainvoke_with_callbacks(
            candidate_model,
            [HumanMessage(content="find papers")],
        )
    finally:
        pop_current_agent_phase(phase_token)
        pop_current_execution(execution_token)
        pop_current_project(project_token)

    assert response.content == "preferred response"
    assert response.response_metadata["provider"] == "preferred"
    assert response.response_metadata["api_base_url"] == (
        "https://preferred.invalid/v1"
    )
    assert db.created_calls[0]["provider_name"] == "fallback"
    assert db.finished_calls[0]["provider_name"] == "preferred"
    assert db.finished_calls[0]["api_base_url"] == "https://preferred.invalid/v1"
    assert db.finished_calls[0]["api_key_hint"] != db.created_calls[0]["api_key_hint"]
    assert pricing_calls[0][0] == "preferred"


@pytest.mark.parametrize("use_pool", [False, True])
async def test_parent_cancellation_drains_provider_task(monkeypatch, use_pool):
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocking_call(*args, **kwargs):
        del args, kwargs
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    class _BlockingLlm:
        _provider_alias = "test-provider"
        _requested_model = "test-model"

        async def ainvoke(self, input, config=None, **kwargs):
            del input, config, kwargs
            return await blocking_call()

    if use_pool:
        router = SimpleNamespace(acompletion=blocking_call)
        pool = SimpleNamespace(router=router)
        monkeypatch.setattr(
            "academic_cluster.services.provider_pool.get_llm_pool",
            lambda: pool,
        )
    else:

        def unavailable_pool():
            raise RuntimeError("pool unavailable")

        monkeypatch.setattr(
            "academic_cluster.services.provider_pool.get_llm_pool",
            unavailable_pool,
        )

    monkeypatch.setattr(
        "academic_cluster.services.llm_client._get_llm_request_gate",
        lambda: (BoundedFifoGate(capacity=1, max_waiters=1), 1.0),
    )

    outer = asyncio.create_task(
        ainvoke_with_callbacks(_BlockingLlm(), "cancel me", timeout=30)
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    outer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await outer

    await asyncio.wait_for(cancelled.wait(), timeout=1)


async def test_timeout_cancels_and_drains_fallback_task(monkeypatch):
    cancelled = asyncio.Event()

    class _TimeoutLlm:
        _provider_alias = "test-provider"

        async def ainvoke(self, input, config=None, **kwargs):
            del input, config, kwargs
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

    def unavailable_pool():
        raise RuntimeError("pool unavailable")

    monkeypatch.setattr(
        "academic_cluster.services.provider_pool.get_llm_pool",
        unavailable_pool,
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client._get_llm_request_gate",
        lambda: (BoundedFifoGate(capacity=1, max_waiters=1), 1.0),
    )

    with pytest.raises(TimeoutError):
        await ainvoke_with_callbacks(_TimeoutLlm(), "timeout", timeout=0.01)

    assert cancelled.is_set()


async def test_llm_gate_rejects_overload_before_a_second_provider_call(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    class _BlockingLlm:
        _provider_alias = "test-provider"

        async def ainvoke(self, input, config=None, **kwargs):
            del input, config, kwargs
            started.set()
            await release.wait()
            return _FakeResponse()

    def unavailable_pool():
        raise RuntimeError("pool unavailable")

    gate = BoundedFifoGate(capacity=1, max_waiters=0)
    monkeypatch.setattr(
        "academic_cluster.services.provider_pool.get_llm_pool",
        unavailable_pool,
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client._get_llm_request_gate",
        lambda: (gate, 1.0),
    )

    first = asyncio.create_task(ainvoke_with_callbacks(_BlockingLlm(), "first"))
    await started.wait()
    with pytest.raises(ConcurrencyQueueFullError):
        await ainvoke_with_callbacks(_BlockingLlm(), "second")

    release.set()
    await first


async def test_ainvoke_records_error_call(monkeypatch):
    db = _FakeDb()

    def fake_get_database():
        return db

    monkeypatch.setattr(
        "academic_cluster.services.database.get_database", fake_get_database
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client._get_llm_request_gate",
        lambda: (BoundedFifoGate(capacity=1, max_waiters=1), 1.0),
    )

    project_token = push_current_project("project-1")
    execution_token = push_current_execution("execution-1")
    phase_token = push_current_agent_phase("peer_review")
    try:
        try:
            await ainvoke_with_callbacks(_FailingLlm(), "hello")
        except RuntimeError:
            pass
    finally:
        pop_current_agent_phase(phase_token)
        pop_current_execution(execution_token)
        pop_current_project(project_token)

    assert db.created_calls
    assert db.finished_calls
    assert db.finished_calls[0]["status"] == "error"
    assert "boom" in (db.finished_calls[0]["error_message"] or "")


class _FakeRow(tuple):
    pass


class _FakeResult:
    def fetchall(self):
        return [
            _FakeRow(
                (
                    "2026-06-15",
                    402,
                    2018871,
                    0.0,
                    2018871,
                    0,
                    0,
                    0.0,
                    0.0,
                    0.0,
                    0,
                    0,
                )
            )
        ]


class _FakeSession:
    def __init__(self):
        self.statements = []
        self.statement = None
        self.params = None

    async def execute(self, statement, params):
        self.statement = str(statement)
        self.statements.append(str(statement))
        self.params = params
        return _FakeResult()


class _FakeSessionContext:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeTrendDb:
    def __init__(self):
        self.fake_session = _FakeSession()

    def session(self):
        return _FakeSessionContext(self.fake_session)


class _PricingSession:
    def __init__(self):
        self.calls = []

    async def execute(self, statement, params):
        self.calls.append((str(statement), params))
        if "display_name" in str(statement):

            class _Row:
                def fetchone(self_inner):
                    return None

            return _Row()
        if "WHERE model = :model" in str(statement):

            class _Row:
                def fetchone(self_inner):
                    return None

            return _Row()

        class _Row:
            def fetchone(self_inner):
                return (0.2, 0.4)

        return _Row()


class _PricingDb:
    def __init__(self):
        self.fake_session = _PricingSession()

    def session(self):
        return _FakeSessionContext(self.fake_session)


async def test_usage_trend_falls_back_to_pipeline_run_summaries():
    db = _FakeTrendDb()

    response = await get_usage_trend(
        days=7,
        current_user={"id": "user-1"},
        db=db,
    )

    assert response.trend[0].call_count == 402
    assert response.trend[0].total_tokens == 2018871
    assert "run_daily" in db.fake_session.statement
    assert "NOT EXISTS" in db.fake_session.statement


class _FakeCallsCountResult:
    def scalar(self):
        return 0


class _FakeCallsRowsResult:
    def fetchall(self):
        return []


class _FakeCallsSession(_FakeSession):
    def __init__(self):
        super().__init__()
        self._index = 0

    async def execute(self, statement, params):
        self.statement = str(statement)
        self.statements.append(str(statement))
        self.params = params
        self._index += 1
        if self._index == 1:
            return _FakeCallsCountResult()
        return _FakeCallsRowsResult()


class _FakeCallsDb:
    def __init__(self):
        self.fake_session = _FakeCallsSession()

    def session(self):
        return _FakeSessionContext(self.fake_session)


async def test_usage_calls_filters_by_call_project_or_run_project():
    db = _FakeCallsDb()

    response = await get_usage_calls(
        project_id="project-1",
        current_user={"id": "user-1"},
        db=db,
    )

    assert response.total == 0
    assert db.fake_session.params["project_id"] == "project-1"
    assert all(
        "COALESCE(lc.project_id, pr.project_id) = :project_id" in statement
        for statement in db.fake_session.statements
    )


async def test_usage_calls_allows_admin_project_lookup():
    db = _FakeCallsDb()

    response = await get_usage_calls(
        project_id="project-1",
        current_user={"id": "admin-1", "role": "admin"},
        db=db,
    )

    assert response.total == 0
    assert db.fake_session.params["project_id"] == "project-1"
    assert all("WHERE TRUE" in statement for statement in db.fake_session.statements)


async def test_get_provider_pricing_handles_namespace_model_alias():
    db = _PricingDb()
    input_price, output_price = await get_provider_pricing(
        db, "gitee-1", "Qwen/Qwen3-8B"
    )
    assert input_price == 0.2
    assert output_price == 0.4
