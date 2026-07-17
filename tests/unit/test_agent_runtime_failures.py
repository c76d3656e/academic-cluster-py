"""Failure and concurrency contracts for the process-local Agent manager."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.exc import IntegrityError

from academic_cluster.agents import agent_graph, checkpoint, orchestrator
from academic_cluster.services import agent_runtime


def _project() -> dict[str, Any]:
    return {
        "id": "project-1",
        "query": "checkpointed agents",
        "config": {"quality_threshold": 82},
    }


class _Database:
    def __init__(self) -> None:
        self.latest: dict[str, Any] | None = None
        self.created: list[dict[str, Any]] = []
        self.execution_updates: list[tuple[str, str, dict[str, Any]]] = []
        self.project_updates: list[tuple[str, str]] = []

    async def get_latest_agent_execution(
        self, _project_id: str
    ) -> dict[str, Any] | None:
        return self.latest

    async def create_agent_execution(self, **kwargs: Any) -> str:
        self.created.append(kwargs)
        return str(kwargs["execution_id"])

    async def update_agent_execution(
        self, execution_id: str, status: str, **kwargs: Any
    ) -> None:
        self.execution_updates.append((execution_id, status, kwargs))

    async def update_project_status(self, project_id: str, status: str) -> None:
        self.project_updates.append((project_id, status))


@pytest.fixture
def healthy_checkpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    async def healthy() -> bool:
        return True

    monkeypatch.setattr(checkpoint, "is_checkpointer_initialized", lambda: True)
    monkeypatch.setattr(checkpoint, "check_runtime_lock_health", healthy)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("values", "next_nodes", "expected"),
    [
        ({}, (), agent_runtime.CheckpointDisposition.MISSING),
        (
            {"status": "running"},
            ("analysis",),
            agent_runtime.CheckpointDisposition.RUNNABLE,
        ),
        (
            {"status": "completed_with_warnings", "errors": []},
            (),
            agent_runtime.CheckpointDisposition.TERMINAL_SUCCESS,
        ),
        (
            {"status": "completed", "errors": ["late failure"]},
            (),
            agent_runtime.CheckpointDisposition.TERMINAL_FAILURE,
        ),
        (
            {"status": "unexpected"},
            (),
            agent_runtime.CheckpointDisposition.TERMINAL_UNKNOWN,
        ),
    ],
)
async def test_checkpoint_inspection_classifies_runnable_and_terminal_states(
    monkeypatch: pytest.MonkeyPatch,
    values: dict[str, Any],
    next_nodes: tuple[str, ...],
    expected: agent_runtime.CheckpointDisposition,
) -> None:
    configs: list[dict[str, Any]] = []

    class _Graph:
        async def aget_state(self, config: dict[str, Any]) -> SimpleNamespace:
            configs.append(config)
            return SimpleNamespace(values=values, next=next_nodes)

    async def compile_graph() -> _Graph:
        return _Graph()

    monkeypatch.setattr(agent_graph, "compile_agent_graph", compile_graph)

    inspection = await agent_runtime._inspect_checkpoint("project-1", "execution-1")

    assert inspection.disposition is expected
    assert inspection.values == values
    assert configs == [agent_graph._thread_config("project-1", "execution-1")]


@pytest.mark.asyncio
@pytest.mark.parametrize(("row", "expected"), [(None, False), (("id",), True)])
async def test_claim_resumable_execution_is_atomic(
    row: Any,
    expected: bool,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    class _Result:
        def fetchone(self) -> Any:
            return row

    class _Session:
        async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
            calls.append((str(statement), params))
            return _Result()

    class _DB:
        @asynccontextmanager
        async def session(self):
            yield _Session()

    claimed = await agent_runtime._claim_resumable_execution(
        _DB(),
        project_id="project-1",
        execution_id="execution-1",
    )

    assert claimed is expected
    assert "status IN ('interrupted', 'failed')" in calls[0][0]
    assert calls[0][1] == {
        "execution_id": "execution-1",
        "project_id": "project-1",
    }


@pytest.mark.asyncio
async def test_start_rejects_unavailable_checkpoint_states(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = agent_runtime.AgentRunManager()
    db = _Database()

    manager._accepting = False
    with pytest.raises(
        agent_runtime.AgentRuntimeUnavailableError, match="shutting down"
    ):
        await manager.start(
            project=_project(), target_papers=5, target_words=2000, db=db
        )

    manager._accepting = True
    monkeypatch.setattr(checkpoint, "is_checkpointer_initialized", lambda: False)
    with pytest.raises(
        agent_runtime.AgentRuntimeUnavailableError, match="not initialized"
    ):
        await manager.start(
            project=_project(), target_papers=5, target_words=2000, db=db
        )

    async def unhealthy() -> bool:
        return False

    monkeypatch.setattr(checkpoint, "is_checkpointer_initialized", lambda: True)
    monkeypatch.setattr(checkpoint, "check_runtime_lock_health", unhealthy)
    with pytest.raises(agent_runtime.AgentRuntimeUnavailableError, match="unavailable"):
        await manager.start(
            project=_project(), target_papers=5, target_words=2000, db=db
        )


@pytest.mark.asyncio
async def test_start_rejects_deleting_or_locally_running_project(
    healthy_checkpoint: None,
) -> None:
    del healthy_checkpoint
    manager = agent_runtime.AgentRunManager()
    db = _Database()
    manager._deleting_projects.add("project-1")

    with pytest.raises(
        agent_runtime.AgentRuntimeUnavailableError, match="being deleted"
    ):
        await manager.start(
            project=_project(), target_papers=5, target_words=2000, db=db
        )

    manager._deleting_projects.clear()
    blocker = asyncio.create_task(asyncio.Event().wait())
    manager._tasks["project-1"] = blocker
    try:
        with pytest.raises(agent_runtime.AgentAlreadyRunningError):
            await manager.start(
                project=_project(), target_papers=5, target_words=2000, db=db
            )
    finally:
        blocker.cancel()
        await asyncio.gather(blocker, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("latest", [None, {"id": "done", "status": "succeeded"}])
async def test_resume_requires_interrupted_or_failed_execution(
    healthy_checkpoint: None,
    latest: dict[str, Any] | None,
) -> None:
    del healthy_checkpoint
    manager = agent_runtime.AgentRunManager()
    db = _Database()
    db.latest = latest

    with pytest.raises(
        agent_runtime.AgentCheckpointNotFoundError, match="No resumable"
    ):
        await manager.start(
            project=_project(),
            target_papers=5,
            target_words=2000,
            resume=True,
            db=db,
        )


@pytest.mark.asyncio
async def test_resume_rejects_database_active_execution(
    healthy_checkpoint: None,
) -> None:
    del healthy_checkpoint
    manager = agent_runtime.AgentRunManager()
    db = _Database()
    db.latest = {"id": "running", "status": "pending"}

    with pytest.raises(agent_runtime.AgentAlreadyRunningError):
        await manager.start(
            project=_project(),
            target_papers=5,
            target_words=2000,
            resume=True,
            db=db,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("disposition", "message"),
    [
        (agent_runtime.CheckpointDisposition.MISSING, "has no checkpoint"),
        (
            agent_runtime.CheckpointDisposition.TERMINAL_UNKNOWN,
            "without a terminal status",
        ),
    ],
)
async def test_interrupted_resume_rejects_unusable_checkpoint(
    monkeypatch: pytest.MonkeyPatch,
    healthy_checkpoint: None,
    disposition: agent_runtime.CheckpointDisposition,
    message: str,
) -> None:
    del healthy_checkpoint
    manager = agent_runtime.AgentRunManager()
    db = _Database()
    db.latest = {"id": "interrupted", "status": "interrupted"}

    async def inspect(*_args: Any) -> agent_runtime.CheckpointInspection:
        return agent_runtime.CheckpointInspection(disposition, {"status": "unknown"})

    monkeypatch.setattr(agent_runtime, "_inspect_checkpoint", inspect)

    with pytest.raises(agent_runtime.AgentCheckpointNotFoundError, match=message):
        await manager.start(
            project=_project(),
            target_papers=5,
            target_words=2000,
            resume=True,
            db=db,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("claim_mode", ["lost", "conflict"])
async def test_runnable_resume_requires_successful_database_claim(
    monkeypatch: pytest.MonkeyPatch,
    healthy_checkpoint: None,
    claim_mode: str,
) -> None:
    del healthy_checkpoint
    manager = agent_runtime.AgentRunManager()
    db = _Database()
    db.latest = {"id": "interrupted", "status": "interrupted"}

    async def inspect(*_args: Any) -> agent_runtime.CheckpointInspection:
        return agent_runtime.CheckpointInspection(
            agent_runtime.CheckpointDisposition.RUNNABLE,
            {"status": "running"},
        )

    async def claim(*_args: Any, **_kwargs: Any) -> bool:
        if claim_mode == "conflict":
            raise IntegrityError("UPDATE", {}, RuntimeError("duplicate"))
        return False

    monkeypatch.setattr(agent_runtime, "_inspect_checkpoint", inspect)
    monkeypatch.setattr(agent_runtime, "_claim_resumable_execution", claim)

    with pytest.raises(agent_runtime.AgentAlreadyRunningError):
        await manager.start(
            project=_project(),
            target_papers=5,
            target_words=2000,
            resume=True,
            db=db,
        )


@pytest.mark.asyncio
async def test_new_execution_maps_unique_conflict_to_already_running(
    monkeypatch: pytest.MonkeyPatch,
    healthy_checkpoint: None,
) -> None:
    del healthy_checkpoint
    manager = agent_runtime.AgentRunManager()

    class _ConflictDatabase(_Database):
        async def create_agent_execution(self, **kwargs: Any) -> str:
            del kwargs
            raise IntegrityError("INSERT", {}, RuntimeError("duplicate"))

    monkeypatch.setattr(agent_runtime.uuid, "uuid4", lambda: "execution-new")

    with pytest.raises(agent_runtime.AgentAlreadyRunningError):
        await manager.start(
            project=_project(),
            target_papers=5,
            target_words=2000,
            db=_ConflictDatabase(),
        )


@pytest.mark.asyncio
async def test_start_tolerates_project_status_publication_failure(
    monkeypatch: pytest.MonkeyPatch,
    healthy_checkpoint: None,
) -> None:
    del healthy_checkpoint
    manager = agent_runtime.AgentRunManager()
    run_calls: list[dict[str, Any]] = []

    class _StatusDatabase(_Database):
        async def update_project_status(self, project_id: str, status: str) -> None:
            del project_id, status
            raise OSError("status temporarily unavailable")

    async def run(**kwargs: Any) -> None:
        run_calls.append(kwargs)

    monkeypatch.setattr(manager, "_run", run)
    execution_id = await manager.start(
        project=_project(),
        target_papers=5,
        target_words=2000,
        db=_StatusDatabase(),
    )
    await manager.wait("project-1")

    assert run_calls[0]["execution_id"] == execution_id


@pytest.mark.asyncio
async def test_background_failed_result_persists_error_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = agent_runtime.AgentRunManager()
    db = _Database()

    class _Orchestrator:
        async def run(self, **_kwargs: Any) -> dict[str, Any]:
            return {
                "status": "failed",
                "warnings": ["partial"],
                "errors": ["quality gate failed"],
                "quality_score": 61.5,
            }

    monkeypatch.setattr(
        orchestrator, "create_orchestrator", lambda **_kw: _Orchestrator()
    )

    await manager._run(
        project=_project(),
        execution_id="execution-1",
        target_papers=5,
        target_words=2000,
        sse_manager=None,
        resume=False,
        db=db,
    )

    assert db.execution_updates[-1] == (
        "execution-1",
        "failed",
        {
            "output_state": {
                "status": "failed",
                "warnings": ["partial"],
                "errors": ["quality gate failed"],
            },
            "quality_score": 61.5,
            "error_message": "quality gate failed",
        },
    )
    assert db.project_updates == [("project-1", "failed")]


@pytest.mark.asyncio
async def test_background_exception_is_persisted_and_reported_to_sse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = agent_runtime.AgentRunManager()
    db = _Database()
    errors: list[tuple[str, str]] = []

    class _Orchestrator:
        async def run(self, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("provider failed")

    class _SSE:
        async def send_error(self, project_id: str, error: str) -> None:
            errors.append((project_id, error))

    monkeypatch.setattr(
        orchestrator, "create_orchestrator", lambda **_kw: _Orchestrator()
    )

    await manager._run(
        project=_project(),
        execution_id="execution-1",
        target_papers=5,
        target_words=2000,
        sse_manager=_SSE(),
        resume=False,
        db=db,
    )

    assert db.execution_updates[-1] == (
        "execution-1",
        "failed",
        {"error_message": "provider failed"},
    )
    assert db.project_updates == [("project-1", "failed")]
    assert errors == [("project-1", "provider failed")]


@pytest.mark.asyncio
async def test_background_cancellation_persists_interruption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = agent_runtime.AgentRunManager()
    db = _Database()
    started = asyncio.Event()

    class _Orchestrator:
        async def run(self, **_kwargs: Any) -> dict[str, Any]:
            started.set()
            await asyncio.Event().wait()
            return {}

    monkeypatch.setattr(
        orchestrator, "create_orchestrator", lambda **_kw: _Orchestrator()
    )
    task = asyncio.create_task(
        manager._run(
            project=_project(),
            execution_id="execution-1",
            target_papers=5,
            target_words=2000,
            sse_manager=None,
            resume=False,
            db=db,
        )
    )
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert db.execution_updates[-1][1] == "interrupted"
    assert db.project_updates == [("project-1", "interrupted")]


@pytest.mark.asyncio
async def test_cancel_and_project_deletion_manage_active_tasks() -> None:
    manager = agent_runtime.AgentRunManager()

    with pytest.raises(agent_runtime.AgentNotRunningError):
        await manager.cancel("missing")

    first = asyncio.create_task(asyncio.Event().wait())
    manager._tasks["first"] = first
    await manager.cancel("first")
    assert first.cancelled()

    second = asyncio.create_task(asyncio.Event().wait())
    manager._tasks["second"] = second
    await manager.begin_project_deletion("second")
    assert second.cancelled()
    assert "second" in manager._deleting_projects
    await manager.end_project_deletion("second")
    assert "second" not in manager._deleting_projects


@pytest.mark.asyncio
async def test_shutdown_and_singleton_close_cancel_all_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = agent_runtime.AgentRunManager()
    first = asyncio.create_task(asyncio.Event().wait())
    second = asyncio.create_task(asyncio.Event().wait())
    manager._tasks.update({"first": first, "second": second})
    manager._deleting_projects.add("first")
    assert manager.is_running("first")

    await manager.shutdown()

    assert first.cancelled() and second.cancelled()
    assert not manager.is_running("first")
    assert manager._tasks == {}
    assert manager._deleting_projects == set()

    monkeypatch.setattr(agent_runtime, "_agent_run_manager", None)
    singleton = agent_runtime.get_agent_run_manager()
    assert singleton is agent_runtime.get_agent_run_manager()
    await agent_runtime.close_agent_run_manager()
    assert agent_runtime._agent_run_manager is None
    assert not singleton._accepting
