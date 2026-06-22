from typing import ClassVar

from academic_cluster.api.admin.providers import get_provider_pricing
from academic_cluster.api.console.usage import get_usage_calls, get_usage_trend
from academic_cluster.services.llm_client import ainvoke_with_callbacks
from academic_cluster.services.observability import PipelineTracker, set_current_tracker


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
        self.created_nodes = []
        self.created_calls = []
        self.finished_calls = []

    async def create_node_execution(self, *args):
        self.created_nodes.append(args)
        return "node-1"

    async def create_llm_call(self, **kwargs):
        self.created_calls.append(kwargs)
        return "call-1"

    async def finish_llm_call(self, **kwargs):
        self.finished_calls.append(kwargs)


class _FailingLlm:
    _provider_alias = "test-provider"

    async def ainvoke(self, input, config=None, **kwargs):
        raise RuntimeError("boom")


async def test_ainvoke_persists_llm_call_without_node_execution(monkeypatch):
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
        "academic_cluster.services.llm_client._get_llm_queue_semaphore",
        lambda: __import__("asyncio").Semaphore(1),
    )

    tracker = PipelineTracker(project_id="project-1")
    tracker.run_id = "run-1"
    set_current_tracker(tracker)

    try:
        await ainvoke_with_callbacks(_FakeLlm(), "hello")
    finally:
        set_current_tracker(None)

    assert db.created_calls
    assert db.created_nodes == [("run-1", "unknown", "llm")]
    assert db.created_calls[0]["pipeline_run_id"] == "run-1"
    assert db.created_calls[0]["node_execution_id"] == "node-1"
    assert db.created_calls[0]["provider_name"] == "test-provider"
    assert db.created_calls[0]["project_id"] == "project-1"
    assert db.created_calls[0]["node_name"] == "unknown"
    assert db.created_calls[0]["requested_model"] == "test-model"
    assert db.created_calls[0]["upstream_model"] == "test-model"
    assert db.created_calls[0]["status"] == "running"
    assert db.finished_calls[0]["prompt_tokens"] == 11
    assert db.finished_calls[0]["completion_tokens"] == 7
    assert db.finished_calls[0]["cost"] == 0.000005
    assert db.finished_calls[0]["input_price_per_m"] == 0.2
    assert db.finished_calls[0]["output_price_per_m"] == 0.4


async def test_ainvoke_records_error_call(monkeypatch):
    db = _FakeDb()

    def fake_get_database():
        return db

    monkeypatch.setattr(
        "academic_cluster.services.database.get_database", fake_get_database
    )
    monkeypatch.setattr(
        "academic_cluster.services.llm_client._get_llm_queue_semaphore",
        lambda: __import__("asyncio").Semaphore(1),
    )

    tracker = PipelineTracker(project_id="project-1")
    tracker.run_id = "run-1"
    set_current_tracker(tracker)

    try:
        try:
            await ainvoke_with_callbacks(_FailingLlm(), "hello")
        except RuntimeError:
            pass
    finally:
        set_current_tracker(None)

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
