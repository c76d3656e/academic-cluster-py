"""Checkpoint storage must acquire, monitor, and release its singleton lock."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from psycopg.conninfo import conninfo_to_dict

from academic_cluster.agents import agent_graph, checkpoint


class _Cursor:
    def __init__(self, row: dict[str, Any] | None = None) -> None:
        self.row = row

    async def fetchone(self) -> dict[str, Any] | None:
        return self.row


class _Connection:
    def __init__(self, *, acquired: bool = True) -> None:
        self.acquired = acquired
        self.closed = False
        self.statements: list[tuple[str, Any]] = []
        self.close_calls = 0

    async def execute(self, sql: str, params: Any = None) -> _Cursor:
        self.statements.append((sql, params))
        if "pg_try_advisory_lock" in sql:
            return _Cursor({"acquired": self.acquired})
        return _Cursor()

    async def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _Pool:
    instances: ClassVar[list[_Pool]] = []

    @staticmethod
    async def check_connection(_connection: Any) -> None:
        return None

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.lock_connection = _Connection()
        self.setup_connection = _Connection()
        self.returned: list[_Connection] = []
        self.open_calls: list[tuple[bool, int]] = []
        self.close_calls = 0
        type(self).instances.append(self)

    async def open(self, *, wait: bool, timeout: int) -> None:
        self.open_calls.append((wait, timeout))

    async def getconn(self) -> _Connection:
        return self.lock_connection

    async def putconn(self, connection: _Connection) -> None:
        self.returned.append(connection)

    @asynccontextmanager
    async def connection(self):
        yield self.setup_connection

    async def close(self) -> None:
        self.close_calls += 1


class _Saver:
    def __init__(self, pool: _Pool) -> None:
        self.pool = pool
        self.setup_calls = 0

    async def setup(self) -> None:
        self.setup_calls += 1


@pytest.fixture(autouse=True)
def _isolated_checkpoint_globals() -> Any:
    previous = (
        checkpoint._pool,
        checkpoint._checkpointer,
        checkpoint._runtime_lock_connection,
        checkpoint._runtime_lock_monitor,
        checkpoint._runtime_lock_lost,
    )
    checkpoint._pool = None
    checkpoint._checkpointer = None
    checkpoint._runtime_lock_connection = None
    checkpoint._runtime_lock_monitor = None
    checkpoint._runtime_lock_lost = False
    _Pool.instances.clear()
    yield
    monitor = checkpoint._runtime_lock_monitor
    if monitor is not None and not monitor.done():
        monitor.cancel()
    (
        checkpoint._pool,
        checkpoint._checkpointer,
        checkpoint._runtime_lock_connection,
        checkpoint._runtime_lock_monitor,
        checkpoint._runtime_lock_lost,
    ) = previous


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        postgres_host="db.internal",
        postgres_port=5433,
        postgres_db="academic",
        postgres_user="agent user",
        postgres_password="secret with spaces",  # noqa: S106 - conninfo quoting case
    )


def test_checkpoint_conninfo_preserves_all_libpq_fields() -> None:
    fields = conninfo_to_dict(checkpoint.build_checkpoint_conninfo(_settings()))

    assert fields == {
        "user": "agent user",
        "password": "secret with spaces",
        "dbname": "academic",
        "host": "db.internal",
        "port": "5433",
        "connect_timeout": "10",
        "application_name": "academic-cluster-checkpoint",
    }


@pytest.mark.asyncio
async def test_runtime_lock_acquisition_releases_connection_when_denied() -> None:
    pool = _Pool()
    pool.lock_connection.acquired = False

    with pytest.raises(RuntimeError, match="exactly one application worker"):
        await checkpoint._acquire_runtime_lock(pool)  # type: ignore[arg-type]

    assert pool.returned == [pool.lock_connection]


@pytest.mark.asyncio
async def test_runtime_lock_release_returns_connection_even_when_unlock_fails() -> None:
    pool = _Pool()

    async def fail_unlock(sql: str, params: Any = None) -> _Cursor:
        del sql, params
        raise OSError("database disconnected")

    pool.lock_connection.execute = fail_unlock  # type: ignore[method-assign]

    with pytest.raises(OSError, match="disconnected"):
        await checkpoint._release_runtime_lock(  # type: ignore[arg-type]
            pool,
            pool.lock_connection,
        )

    assert pool.returned == [pool.lock_connection]


@pytest.mark.asyncio
async def test_initialize_is_idempotent_and_close_releases_every_resource(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema_pools: list[_Pool] = []
    compile_calls: list[tuple[Any, bool]] = []
    reset_calls = 0

    async def apply_schema(pool: _Pool) -> None:
        schema_pools.append(pool)

    async def compile_graph(saver: Any = None, *, force: bool = False) -> object:
        compile_calls.append((saver, force))
        return object()

    async def reset_graph() -> None:
        nonlocal reset_calls
        reset_calls += 1

    monkeypatch.setattr(checkpoint, "AsyncConnectionPool", _Pool)
    monkeypatch.setattr(checkpoint, "AsyncPostgresSaver", _Saver)
    monkeypatch.setattr(checkpoint, "_apply_agent_schema", apply_schema)
    monkeypatch.setattr(agent_graph, "compile_agent_graph", compile_graph)
    monkeypatch.setattr(agent_graph, "reset_agent_graph", reset_graph)

    saver = await checkpoint.initialize_checkpointer(_settings())
    same_saver = await checkpoint.initialize_checkpointer(_settings())

    assert same_saver is saver
    assert checkpoint.is_checkpointer_initialized()
    assert len(_Pool.instances) == 1
    pool = _Pool.instances[0]
    assert pool.open_calls == [(True, 30)]
    assert schema_pools == [pool]
    assert isinstance(saver, _Saver)
    assert saver.setup_calls == 1
    assert compile_calls == [(saver, True)]
    assert any(sql == "SELECT 1" for sql, _params in pool.lock_connection.statements)

    await checkpoint.close_checkpointer()

    assert reset_calls == 1
    assert pool.returned == [pool.lock_connection]
    assert pool.close_calls == 1
    assert not checkpoint.is_checkpointer_initialized()


@pytest.mark.asyncio
async def test_initialize_failure_releases_lock_and_closes_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def apply_schema(_pool: _Pool) -> None:
        return None

    async def fail_compile(_saver: Any = None, *, force: bool = False) -> None:
        assert force
        raise RuntimeError("graph compile failed")

    monkeypatch.setattr(checkpoint, "AsyncConnectionPool", _Pool)
    monkeypatch.setattr(checkpoint, "AsyncPostgresSaver", _Saver)
    monkeypatch.setattr(checkpoint, "_apply_agent_schema", apply_schema)
    monkeypatch.setattr(agent_graph, "compile_agent_graph", fail_compile)

    with pytest.raises(RuntimeError, match="graph compile failed"):
        await checkpoint.initialize_checkpointer(_settings())

    pool = _Pool.instances[0]
    assert pool.returned == [pool.lock_connection]
    assert pool.close_calls == 1
    assert checkpoint._pool is None
    assert checkpoint._checkpointer is None
    assert checkpoint._runtime_lock_connection is None


@pytest.mark.asyncio
async def test_closed_runtime_lock_fences_once(monkeypatch: pytest.MonkeyPatch) -> None:
    shutdown_calls = 0

    class _Manager:
        async def shutdown(self) -> None:
            nonlocal shutdown_calls
            shutdown_calls += 1

    connection = _Connection()
    connection.closed = True
    checkpoint._checkpointer = object()  # type: ignore[assignment]
    checkpoint._runtime_lock_connection = connection  # type: ignore[assignment]
    monkeypatch.setattr(
        "academic_cluster.services.agent_runtime.get_agent_run_manager",
        lambda: _Manager(),
    )

    assert not await checkpoint.check_runtime_lock_health()
    assert not await checkpoint.check_runtime_lock_health()
    assert shutdown_calls == 1
    assert checkpoint._runtime_lock_lost


@pytest.mark.asyncio
async def test_lock_monitor_exits_after_unhealthy_poll(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    polls = 0

    async def immediate_sleep(_seconds: float) -> None:
        return None

    async def unhealthy() -> bool:
        nonlocal polls
        polls += 1
        return False

    monkeypatch.setattr(asyncio, "sleep", immediate_sleep)
    monkeypatch.setattr(checkpoint, "check_runtime_lock_health", unhealthy)

    await checkpoint._monitor_runtime_lock()

    assert polls == 1
