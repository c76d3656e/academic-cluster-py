"""Tests for the single Agent runtime shared by both API aliases."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from academic_cluster.api import agent_routes, main, routes, sse
from academic_cluster.services import agent_runtime


class _FakeManager:
    def __init__(self) -> None:
        self.start_calls: list[dict[str, Any]] = []
        self.cancel_calls: list[str] = []
        self.error: Exception | None = None
        self.cancel_execution_id = "cancelled-execution"

    async def start(self, **kwargs: Any) -> str:
        if self.error is not None:
            raise self.error
        self.start_calls.append(kwargs)
        return "existing-execution" if kwargs["resume"] else "new-execution"

    async def cancel(self, project_id: str) -> str:
        if self.error is not None:
            raise self.error
        self.cancel_calls.append(project_id)
        return self.cancel_execution_id


class _FakeDB:
    def __init__(self, project: dict[str, Any] | None) -> None:
        self.project = project
        self.latest_execution: dict[str, Any] | None = None
        self.created_executions: list[dict[str, Any]] = []
        self.execution_updates: list[tuple[str, str, dict[str, Any]]] = []
        self.project_statuses: list[tuple[str, str]] = []
        self.saved_projects: list[dict[str, Any]] = []
        self.projects_for_list: list[dict[str, Any]] = []
        self.project_papers: list[dict[str, Any]] = []

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        del project_id
        return self.project

    async def get_latest_agent_execution(
        self, project_id: str
    ) -> dict[str, Any] | None:
        del project_id
        return self.latest_execution

    async def create_agent_execution(self, **kwargs: Any) -> str:
        self.created_executions.append(kwargs)
        return str(kwargs["execution_id"])

    async def save_project(self, data: dict[str, Any]) -> str:
        self.saved_projects.append(data)
        return str(data["id"])

    async def list_projects_by_user(
        self, user_id: str, skip: int, limit: int
    ) -> tuple[list[dict[str, Any]], int]:
        del user_id
        projects = self.projects_for_list[skip : skip + limit]
        return projects, len(self.projects_for_list)

    async def update_agent_execution(
        self, execution_id: str, status: str, **kwargs: Any
    ) -> None:
        self.execution_updates.append((execution_id, status, kwargs))

    async def update_project_status(self, project_id: str, status: str) -> None:
        self.project_statuses.append((project_id, status))

    async def get_project_papers(
        self, project_id: str, *, limit: int = 500
    ) -> list[dict[str, Any]]:
        del project_id
        return self.project_papers[:limit]


def test_removed_legacy_surfaces_are_not_registered() -> None:
    app = main.create_app()
    paths = {getattr(route, "path", "") for route in app.routes}

    assert paths.isdisjoint(
        {
            "/api/ws/{project_id}",
            "/api/projects/{project_id}/outline/confirm",
            "/api/projects/{project_id}/visualization",
            "/api/runs/{run_id}/stats",
            "/api/runs/{run_id}/nodes",
            "/api/runs/{run_id}/llm-calls",
            "/api/usage/summary",
        }
    )


def _project() -> dict[str, Any]:
    return {
        "id": "project-1",
        "user_id": "user-1",
        "query": "checkpointed agents",
        "config": {"target_papers": 12, "target_words": 3456},
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"target_papers": True},
        {"target_words": True},
    ],
)
def test_run_agent_request_rejects_boolean_targets(
    overrides: dict[str, Any],
) -> None:
    with pytest.raises(ValueError):
        agent_routes.RunAgentRequest(project_id="project-1", **overrides)


def _install_manager(monkeypatch: pytest.MonkeyPatch, manager: _FakeManager) -> None:
    monkeypatch.setattr(agent_routes, "get_agent_run_manager", lambda: manager)
    monkeypatch.setattr(routes, "get_agent_run_manager", lambda: manager)
    monkeypatch.setattr(sse, "get_sse_manager", lambda: object())


async def _healthy_checkpoint() -> bool:
    return True


@pytest.mark.asyncio
async def test_project_surfaces_return_only_canonical_public_statuses() -> None:
    user = {"id": "user-1", "role": "user"}
    db = _FakeDB(None)

    created = await routes.create_project(
        routes.CreateProjectRequest(name="Project", query="Topic"),
        current_user=user,
        db=db,  # type: ignore[arg-type]
    )
    assert created.status == "pending"
    assert db.saved_projects[0]["status"] == "created"

    db.projects_for_list = [
        {
            "id": "project-1",
            "name": "Project",
            "query": "Topic",
            "status": "running:agent:writing",
        },
        {
            "id": "project-2",
            "name": "Legacy",
            "query": "Topic",
            "status": "clustering",
        },
    ]
    listed = await routes.list_projects(
        current_user=user,
        db=db,  # type: ignore[arg-type]
    )
    assert [project.status for project in listed.projects] == ["running", "running"]

    db.project = {
        "id": "project-1",
        "user_id": "user-1",
        "name": "Project",
        "query": "Topic",
        "status": "running:agent:writing",
    }
    detail = await routes.get_project_detail(
        "project-1",
        current_user=user,
        db=db,  # type: ignore[arg-type]
    )
    assert detail["status"] == "running"
    assert detail["current_phase"] == "writing"


@pytest.mark.asyncio
async def test_project_sources_are_owner_scoped_and_group_real_papers() -> None:
    db = _FakeDB(_project())
    db.project_papers = [
        {
            "id": "paper-1",
            "source": "arxiv",
            "title": "Agent Observability",
            "authors": [{"name": "A. Researcher"}],
            "year": 2026,
            "doi": "10.1000/example",
            "url": "https://arxiv.org/abs/1234",
            "citation_count": 12,
        },
        {
            "id": "paper-2",
            "source": "arxiv",
            "title": "Reliable Workflows",
            "citation_count": 4,
        },
        {"id": "paper-3", "source": "pubmed", "title": "Clinical Agents"},
    ]

    response = await routes.get_project_sources(
        "project-1",
        current_user={"id": "user-1", "role": "user"},
        db=db,  # type: ignore[arg-type]
    )

    assert response["total"] == 3
    assert [(item["source"], item["count"]) for item in response["sources"]] == [
        ("arxiv", 2),
        ("pubmed", 1),
    ]
    assert response["sources"][0]["papers"][0]["doi"] == "10.1000/example"

    with pytest.raises(HTTPException) as caught:
        await routes.get_project_sources(
            "project-1",
            current_user={"id": "other-user", "role": "user"},
            db=db,  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 403


@pytest.mark.asyncio
async def test_both_start_aliases_delegate_to_the_same_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _FakeManager()
    _install_manager(monkeypatch, manager)
    db = _FakeDB(_project())
    user = {"id": "user-1", "role": "user"}

    agent_response = await agent_routes.run_agent(
        agent_routes.RunAgentRequest(
            project_id="project-1",
            target_papers=20,
            target_words=5000,
        ),
        current_user=user,
        db=db,  # type: ignore[arg-type]
    )
    pipeline_response = await routes.start_pipeline(
        "project-1",
        current_user=user,
        db=db,  # type: ignore[arg-type]
    )

    assert agent_response.execution_id == "new-execution"
    assert pipeline_response["execution_id"] == "new-execution"
    assert [call["resume"] for call in manager.start_calls] == [False, False]
    assert manager.start_calls[0]["target_papers"] == 20
    assert manager.start_calls[1]["target_papers"] == 12
    assert all(call["db"] is db for call in manager.start_calls)


@pytest.mark.asyncio
async def test_both_resume_aliases_return_the_existing_execution_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _FakeManager()
    _install_manager(monkeypatch, manager)
    db = _FakeDB(_project())
    user = {"id": "user-1", "role": "user"}

    agent_response = await agent_routes.resume_agent(
        "project-1",
        current_user=user,
        db=db,  # type: ignore[arg-type]
    )
    pipeline_response = await routes.resume_pipeline(
        "project-1",
        current_user=user,
        db=db,  # type: ignore[arg-type]
    )

    assert agent_response.execution_id == "existing-execution"
    assert pipeline_response["execution_id"] == "existing-execution"
    assert [call["resume"] for call in manager.start_calls] == [True, True]


@pytest.mark.asyncio
async def test_resume_maps_missing_checkpoint_to_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _FakeManager()
    manager.error = agent_runtime.AgentCheckpointNotFoundError("checkpoint missing")
    _install_manager(monkeypatch, manager)
    db = _FakeDB(_project())

    with pytest.raises(HTTPException) as caught:
        await agent_routes.resume_agent(
            "project-1",
            current_user={"id": "user-1", "role": "user"},
            db=db,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_pause_aliases_check_access_and_delegate_to_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _FakeManager()
    _install_manager(monkeypatch, manager)
    db = _FakeDB(_project())
    db.latest_execution = {"id": "stale-execution", "status": "running"}
    user = {"id": "user-1", "role": "user"}

    agent_response = await agent_routes.pause_agent(
        "project-1",
        current_user=user,
        db=db,  # type: ignore[arg-type]
    )
    pipeline_response = await routes.pause_pipeline(
        "project-1",
        current_user=user,
        db=db,  # type: ignore[arg-type]
    )
    assert manager.cancel_calls == ["project-1", "project-1"]
    assert agent_response["execution_id"] == "cancelled-execution"
    assert pipeline_response["execution_id"] == "cancelled-execution"

    with pytest.raises(HTTPException) as caught:
        await routes.pause_pipeline(
            "project-1",
            current_user={"id": "other-user", "role": "user"},
            db=db,  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 403
    assert manager.cancel_calls == ["project-1", "project-1"]


@pytest.mark.asyncio
async def test_status_reads_the_canonical_agent_execution() -> None:
    db = _FakeDB(_project())
    started_at = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
    db.latest_execution = {
        "id": "execution-1",
        "agent_name": "orchestrator",
        "status": "failed",
        "started_at": started_at,
        "finished_at": None,
        "duration_ms": 42,
        "quality_score": 71.5,
        "error_message": "provider unavailable",
    }

    response = await agent_routes.get_agent_status(
        "project-1",
        current_user={"id": "user-1", "role": "user"},
        db=db,  # type: ignore[arg-type]
    )

    assert response.execution_id == "execution-1"
    assert response.status == "failed"
    assert response.started_at == started_at.isoformat()
    assert response.error_message == "provider unavailable"


@pytest.mark.asyncio
async def test_project_status_alias_uses_agent_execution_progress() -> None:
    project = _project()
    project["status"] = "running:agent:writing"
    db = _FakeDB(project)
    db.latest_execution = {
        "id": "execution-1",
        "status": "running",
        "duration_ms": 42,
        "quality_score": None,
        "error_message": None,
    }

    response = await routes.get_project_status(
        "project-1",
        current_user={"id": "user-1", "role": "user"},
        db=db,  # type: ignore[arg-type]
    )

    assert response.status == "running"
    assert response.execution_id == "execution-1"
    assert response.current_phase == "writing"
    assert response.current_node == "writing"
    assert response.progress == {
        "execution_id": "execution-1",
        "status": "running",
        "duration_ms": 42,
        "quality_score": None,
    }


@pytest.mark.asyncio
async def test_pending_execution_is_publicly_running() -> None:
    project = _project()
    project["status"] = "created"
    db = _FakeDB(project)
    db.latest_execution = {
        "id": "execution-1",
        "agent_name": "orchestrator",
        "status": "pending",
        "duration_ms": None,
        "quality_score": None,
        "error_message": None,
    }
    user = {"id": "user-1", "role": "user"}

    agent_status = await agent_routes.get_agent_status(
        "project-1",
        current_user=user,
        db=db,  # type: ignore[arg-type]
    )
    project_status = await routes.get_project_status(
        "project-1",
        current_user=user,
        db=db,  # type: ignore[arg-type]
    )

    assert agent_status.status == "running"
    assert project_status.status == "running"
    assert project_status.current_phase == "supervisor"
    assert project_status.progress == {
        "execution_id": "execution-1",
        "status": "running",
        "duration_ms": None,
        "quality_score": None,
    }


class _Rows:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = [SimpleNamespace(_mapping=row) for row in rows]

    def fetchall(self) -> list[Any]:
        return self._rows


class _LogSession:
    async def execute(self, statement: Any, params: dict[str, Any]) -> _Rows:
        del params
        sql = str(statement)
        created_at = datetime(2026, 7, 17, 8, 0, tzinfo=UTC)
        if "agent_decisions" in sql:
            return _Rows(
                [
                    {
                        "id": "decision-1",
                        "execution_id": "execution-1",
                        "agent_name": "supervisor",
                        "decision_type": "research",
                        "reasoning": "No papers yet",
                        "created_at": created_at,
                    }
                ]
            )
        return _Rows(
            [
                {
                    "id": "tool-1",
                    "execution_id": "execution-1",
                    "agent_name": "research",
                    "tool_name": "search",
                    "input_summary": "query",
                    "output_summary": "12 papers",
                    "duration_ms": 10,
                    "status": "success",
                    "error_message": None,
                    "created_at": created_at,
                }
            ]
        )


class _LogDB(_FakeDB):
    @asynccontextmanager
    async def session(self):  # type: ignore[no-untyped-def]
        yield _LogSession()


@pytest.mark.asyncio
async def test_logs_return_execution_and_agent_schema_fields() -> None:
    response = await agent_routes.get_agent_logs(
        "project-1",
        current_user={"id": "user-1", "role": "user"},
        db=_LogDB(_project()),  # type: ignore[arg-type]
    )

    assert response.decisions[0].execution_id == "execution-1"
    assert response.tool_calls[0].agent_name == "research"
    assert response.tool_calls[0].status == "success"


@pytest.mark.asyncio
async def test_runtime_resume_reuses_database_execution_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = agent_runtime.AgentRunManager()
    db = _FakeDB(_project())
    db.latest_execution = {
        "id": "existing-execution",
        "status": "interrupted",
    }

    async def fake_inspect_checkpoint(
        project_id: str, execution_id: str
    ) -> agent_runtime.CheckpointInspection:
        assert (project_id, execution_id) == ("project-1", "existing-execution")
        return agent_runtime.CheckpointInspection(
            agent_runtime.CheckpointDisposition.RUNNABLE,
            {"status": "running"},
        )

    async def fake_claim(db_arg: Any, **kwargs: str) -> bool:
        assert db_arg is db
        assert kwargs["execution_id"] == "existing-execution"
        return True

    run_calls: list[dict[str, Any]] = []

    async def fake_run(**kwargs: Any) -> None:
        run_calls.append(kwargs)

    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.is_checkpointer_initialized",
        lambda: True,
    )
    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.check_runtime_lock_health",
        _healthy_checkpoint,
    )
    monkeypatch.setattr(agent_runtime, "_inspect_checkpoint", fake_inspect_checkpoint)
    monkeypatch.setattr(agent_runtime, "_claim_resumable_execution", fake_claim)
    monkeypatch.setattr(manager, "_run", fake_run)

    execution_id = await manager.start(
        project=_project(),
        target_papers=12,
        target_words=3456,
        resume=True,
        db=db,
    )
    await manager.wait("project-1")

    assert execution_id == "existing-execution"
    assert run_calls[0]["execution_id"] == "existing-execution"
    assert run_calls[0]["resume"] is True
    assert db.project_statuses == [("project-1", "running:agent:supervisor")]
    await manager.shutdown()


@pytest.mark.asyncio
async def test_runtime_failed_resume_starts_new_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = agent_runtime.AgentRunManager()
    db = _FakeDB(_project())
    db.latest_execution = {
        "id": "failed-execution",
        "status": "failed",
        "input_state": {
            "topic": "original retry topic",
            "target_papers": 27,
            "target_words": 6789,
            "quality_threshold": 88,
        },
    }
    run_calls: list[dict[str, Any]] = []

    async def fake_inspect_checkpoint(
        project_id: str, execution_id: str
    ) -> agent_runtime.CheckpointInspection:
        assert (project_id, execution_id) == ("project-1", "failed-execution")
        return agent_runtime.CheckpointInspection(
            agent_runtime.CheckpointDisposition.TERMINAL_FAILURE,
            {"status": "failed", "errors": ["quality gate failed"]},
        )

    async def fake_run(**kwargs: Any) -> None:
        run_calls.append(kwargs)

    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.is_checkpointer_initialized",
        lambda: True,
    )
    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.check_runtime_lock_health",
        _healthy_checkpoint,
    )
    monkeypatch.setattr(agent_runtime, "_inspect_checkpoint", fake_inspect_checkpoint)
    monkeypatch.setattr(manager, "_run", fake_run)

    execution_id = await manager.start(
        project=_project(),
        target_papers=12,
        target_words=3456,
        resume=True,
        db=db,
    )
    await manager.wait("project-1")

    assert execution_id != "failed-execution"
    assert db.created_executions[0]["input_state"]["retry_of_execution_id"] == (
        "failed-execution"
    )
    assert db.created_executions[0]["input_state"] == {
        "topic": "original retry topic",
        "target_papers": 27,
        "target_words": 6789,
        "quality_threshold": 88.0,
        "retry_of_execution_id": "failed-execution",
    }
    assert run_calls[0]["execution_id"] == execution_id
    assert run_calls[0]["resume"] is False
    assert run_calls[0]["topic"] == "original retry topic"
    assert run_calls[0]["target_papers"] == 27
    assert run_calls[0]["target_words"] == 6789
    assert run_calls[0]["quality_threshold"] == 88.0
    await manager.shutdown()


@pytest.mark.asyncio
async def test_terminal_checkpoint_is_not_resumable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Graph:
        async def aget_state(self, config: Any) -> SimpleNamespace:
            del config
            return SimpleNamespace(values={"status": "failed"}, next=())

    async def fake_compile() -> _Graph:
        return _Graph()

    monkeypatch.setattr(
        "academic_cluster.agents.agent_graph.compile_agent_graph", fake_compile
    )

    inspection = await agent_runtime._inspect_checkpoint("project-1", "execution-1")

    assert (
        inspection.disposition is agent_runtime.CheckpointDisposition.TERMINAL_FAILURE
    )


@pytest.mark.asyncio
async def test_runtime_failed_with_runnable_checkpoint_resumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = agent_runtime.AgentRunManager()
    db = _FakeDB(_project())
    db.latest_execution = {"id": "failed-execution", "status": "failed"}
    run_calls: list[dict[str, Any]] = []

    async def fake_inspect_checkpoint(
        _project_id: str, _execution_id: str
    ) -> agent_runtime.CheckpointInspection:
        return agent_runtime.CheckpointInspection(
            agent_runtime.CheckpointDisposition.RUNNABLE,
            {"status": "running"},
        )

    async def fake_claim(_db: Any, **_kwargs: str) -> bool:
        return True

    async def fake_run(**kwargs: Any) -> None:
        run_calls.append(kwargs)

    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.is_checkpointer_initialized",
        lambda: True,
    )
    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.check_runtime_lock_health",
        _healthy_checkpoint,
    )
    monkeypatch.setattr(agent_runtime, "_inspect_checkpoint", fake_inspect_checkpoint)
    monkeypatch.setattr(agent_runtime, "_claim_resumable_execution", fake_claim)
    monkeypatch.setattr(manager, "_run", fake_run)

    execution_id = await manager.start(
        project=_project(),
        target_papers=12,
        target_words=3456,
        resume=True,
        db=db,
    )
    await manager.wait("project-1")

    assert execution_id == "failed-execution"
    assert db.created_executions == []
    assert run_calls[0]["resume"] is True
    await manager.shutdown()


@pytest.mark.asyncio
async def test_runtime_interrupted_terminal_success_reconciles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = agent_runtime.AgentRunManager()
    db = _FakeDB(_project())
    db.latest_execution = {"id": "completed-execution", "status": "interrupted"}

    async def fake_inspect_checkpoint(
        _project_id: str, _execution_id: str
    ) -> agent_runtime.CheckpointInspection:
        return agent_runtime.CheckpointInspection(
            agent_runtime.CheckpointDisposition.TERMINAL_SUCCESS,
            {
                "status": "completed_with_warnings",
                "warnings": ["review threshold not met"],
                "errors": [],
                "quality_score": 72.5,
            },
        )

    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.is_checkpointer_initialized",
        lambda: True,
    )
    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.check_runtime_lock_health",
        _healthy_checkpoint,
    )
    monkeypatch.setattr(agent_runtime, "_inspect_checkpoint", fake_inspect_checkpoint)

    execution_id = await manager.start(
        project=_project(),
        target_papers=12,
        target_words=3456,
        resume=True,
        db=db,
    )

    assert execution_id == "completed-execution"
    assert db.created_executions == []
    assert db.execution_updates == [
        (
            "completed-execution",
            "succeeded",
            {
                "output_state": {
                    "status": "completed_with_warnings",
                    "warnings": ["review threshold not met"],
                    "errors": [],
                },
                "quality_score": 72.5,
            },
        )
    ]
    assert db.project_statuses == [("project-1", "completed")]
    await manager.shutdown()


@pytest.mark.asyncio
async def test_runtime_uses_provider_pool_instead_of_project_agent_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = agent_runtime.AgentRunManager()
    db = _FakeDB(_project())
    project = _project()
    project["config"] = {
        "agent_model": "misleading-project-model",
        "quality_threshold": 83.5,
    }
    create_kwargs: list[dict[str, Any]] = []

    class _Orchestrator:
        async def run(self, **kwargs: Any) -> dict[str, Any]:
            assert kwargs["project_id"] == "project-1"
            return {"status": "completed", "warnings": [], "errors": []}

    def fake_create_orchestrator(**kwargs: Any) -> _Orchestrator:
        create_kwargs.append(kwargs)
        return _Orchestrator()

    monkeypatch.setattr(
        "academic_cluster.agents.orchestrator.create_orchestrator",
        fake_create_orchestrator,
    )

    await manager._run(
        project=project,
        execution_id="execution-1",
        target_papers=12,
        target_words=3456,
        sse_manager=object(),
        resume=False,
        db=db,
    )

    assert create_kwargs == [{"quality_threshold": 83.5}]
    assert db.project_statuses == [("project-1", "completed")]


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, 75.0),
        ({"quality_threshold": "82.5"}, 82.5),
        ({"quality_threshold": -1}, 0.0),
        ({"quality_threshold": 101}, 100.0),
        ({"quality_threshold": "invalid"}, 75.0),
        ({"quality_threshold": float("nan")}, 75.0),
        ({"quality_threshold": True}, 75.0),
        ("invalid-config", 75.0),
    ],
)
def test_quality_threshold_config_is_finite_and_bounded(
    config: Any,
    expected: float,
) -> None:
    assert agent_runtime._resolve_quality_threshold(config) == expected


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, (50, 12000)),
        ({"target_papers": "27", "target_words": "6789"}, (27, 6789)),
        ({"target_papers": 0, "target_words": 999}, (1, 1000)),
        ({"target_papers": 501, "target_words": 100001}, (500, 100000)),
        ({"target_papers": True, "target_words": False}, (50, 12000)),
        ({"target_papers": float("inf"), "target_words": None}, (50, 12000)),
        ("invalid-config", (50, 12000)),
    ],
)
def test_agent_targets_are_bounded_without_treating_booleans_as_ints(
    config: Any,
    expected: tuple[int, int],
) -> None:
    assert agent_runtime.resolve_agent_targets(config) == expected


@pytest.mark.asyncio
async def test_shutdown_fences_start_while_acceptance_status_is_awaiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = agent_runtime.AgentRunManager()

    class _BlockingStatusDB(_FakeDB):
        def __init__(self) -> None:
            super().__init__(_project())
            self.status_started = asyncio.Event()
            self.release_status = asyncio.Event()

        async def update_project_status(self, project_id: str, status: str) -> None:
            if status == "running:agent:supervisor":
                self.status_started.set()
                await self.release_status.wait()
            await super().update_project_status(project_id, status)

    db = _BlockingStatusDB()
    run_called = False

    async def fail_if_run(**_kwargs: Any) -> None:
        nonlocal run_called
        run_called = True

    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.is_checkpointer_initialized",
        lambda: True,
    )
    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.check_runtime_lock_health",
        _healthy_checkpoint,
    )
    monkeypatch.setattr(manager, "_run", fail_if_run)

    start_task = asyncio.create_task(
        manager.start(
            project=_project(),
            target_papers=12,
            target_words=3456,
            db=db,
        )
    )
    await db.status_started.wait()
    shutdown_task = asyncio.create_task(manager.shutdown())
    await asyncio.sleep(0)
    assert not manager._accepting
    db.release_status.set()

    with pytest.raises(
        agent_runtime.AgentRuntimeUnavailableError,
        match="stopped before execution",
    ):
        await start_task
    await shutdown_task

    assert not run_called
    assert db.execution_updates[-1][1] == "interrupted"
    assert db.project_statuses == [
        ("project-1", "running:agent:supervisor"),
        ("project-1", "interrupted"),
    ]


@pytest.mark.asyncio
async def test_shutdown_drains_manager_before_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from academic_cluster import services
    from academic_cluster.agents import checkpoint
    from academic_cluster.services import provider_pool

    calls: list[str] = []

    def closer(name: str):  # type: ignore[no-untyped-def]
        async def close() -> None:
            calls.append(name)

        return close

    monkeypatch.setattr(agent_runtime, "close_agent_run_manager", closer("manager"))
    monkeypatch.setattr(provider_pool, "close_pools", closer("providers"))
    monkeypatch.setattr(checkpoint, "close_checkpointer", closer("checkpoint"))
    monkeypatch.setattr(services, "close_database", closer("database"))
    monkeypatch.setattr(services, "close_cache", closer("cache"))
    monkeypatch.setattr(services, "close_vector_store", closer("vector"))

    await main._shutdown_application_services()

    assert calls == [
        "manager",
        "providers",
        "checkpoint",
        "database",
        "cache",
        "vector",
    ]


@pytest.mark.asyncio
async def test_startup_failure_releases_initialized_services(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failure before ASGI yield must not retain the Agent singleton lock."""

    from academic_cluster import services
    from academic_cluster.agents import checkpoint

    events: list[str] = []

    class _Settings:
        log_level = "INFO"
        is_production = True

        def validate_security(self) -> None:
            return None

    async def initialize(_settings: Any) -> None:
        events.append("checkpoint-initialized")

    async def seed(*_args: Any) -> None:
        return None

    async def fail_schema(_db: Any) -> None:
        raise RuntimeError("schema unavailable")

    async def shutdown() -> None:
        events.append("shutdown")

    monkeypatch.setattr(main, "get_settings", _Settings)
    monkeypatch.setattr(services, "get_database", object)
    monkeypatch.setattr(services, "get_cache", object)
    monkeypatch.setattr(services, "get_vector_store", object)
    monkeypatch.setattr(checkpoint, "initialize_checkpointer", initialize)
    monkeypatch.setattr(main, "_seed_admin", seed)
    monkeypatch.setattr(main, "_ensure_observability_schema", fail_schema)
    monkeypatch.setattr(main, "_shutdown_application_services", shutdown)

    with pytest.raises(
        RuntimeError,
        match="Failed to initialize production schemas or providers",
    ):
        async with main.lifespan(None):  # type: ignore[arg-type]
            pytest.fail("startup failure must happen before ASGI yield")

    assert events == ["checkpoint-initialized", "shutdown"]


@pytest.mark.asyncio
async def test_agent_stale_cleanup_survives_legacy_pipeline_cleanup_failure() -> None:
    class _Database:
        agent_cleanup_called = False

        @asynccontextmanager
        async def session(self):  # type: ignore[no-untyped-def]
            raise RuntimeError("legacy pipeline table unavailable")
            yield

        async def cleanup_stale_agent_executions(self) -> int:
            self.agent_cleanup_called = True
            return 1

    database = _Database()

    await main._cleanup_stale_executions(database)

    assert database.agent_cleanup_called
