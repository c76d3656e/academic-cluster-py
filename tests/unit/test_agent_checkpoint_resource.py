"""The Agent database migration must ship with every runtime layout."""

from contextlib import asynccontextmanager

import pytest

from academic_cluster.agents import checkpoint
from academic_cluster.agents.checkpoint import _read_agent_schema_sql


def test_agent_schema_sql_is_available() -> None:
    sql = _read_agent_schema_sql()

    assert "CREATE TABLE IF NOT EXISTS agent_executions" in sql
    assert "CREATE TABLE IF NOT EXISTS agent_tool_calls" in sql
    assert "CREATE TABLE IF NOT EXISTS project_papers" in sql


class _Cursor:
    async def fetchall(self) -> list[dict[str, str]]:
        return [
            {"thread_id": "academic-cluster:agent:v1:project-1:execution-1"},
            {"thread_id": "academic-cluster:agent:v1:project-1:execution-2"},
        ]


class _Connection:
    def __init__(self) -> None:
        self.params: tuple[str, str, str] | None = None

    async def execute(self, sql: str, params: tuple[str, str, str]) -> _Cursor:
        assert "FROM checkpoints" in sql
        assert "FROM checkpoint_blobs" in sql
        assert "FROM checkpoint_writes" in sql
        self.params = params
        return _Cursor()


class _Pool:
    def __init__(self) -> None:
        self.connection_instance = _Connection()

    @asynccontextmanager
    async def connection(self):
        yield self.connection_instance


class _Saver:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


async def test_delete_project_checkpoints_uses_project_thread_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = _Pool()
    saver = _Saver()
    monkeypatch.setattr(checkpoint, "_pool", pool)
    monkeypatch.setattr(checkpoint, "_checkpointer", saver)

    deleted = await checkpoint.delete_project_checkpoints("project-1")

    assert deleted == 2
    assert pool.connection_instance.params == (
        "academic-cluster:agent:v1:project-1:%",
        "academic-cluster:agent:v1:project-1:%",
        "academic-cluster:agent:v1:project-1:%",
    )
    assert saver.deleted == [
        "academic-cluster:agent:v1:project-1:execution-1",
        "academic-cluster:agent:v1:project-1:execution-2",
    ]


async def test_runtime_lock_loss_fences_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from academic_cluster.services import agent_runtime

    class _BrokenConnection:
        closed = False

        async def execute(self, _sql: str) -> None:
            raise OSError("connection lost")

    class _Manager:
        def __init__(self) -> None:
            self.shutdown_called = False

        async def shutdown(self) -> None:
            self.shutdown_called = True

    manager = _Manager()
    monkeypatch.setattr(checkpoint, "_checkpointer", object())
    monkeypatch.setattr(checkpoint, "_runtime_lock_connection", _BrokenConnection())
    monkeypatch.setattr(checkpoint, "_runtime_lock_lost", False)
    monkeypatch.setattr(agent_runtime, "get_agent_run_manager", lambda: manager)

    healthy = await checkpoint.check_runtime_lock_health()

    assert not healthy
    assert manager.shutdown_called
    assert not checkpoint.is_checkpointer_initialized()
