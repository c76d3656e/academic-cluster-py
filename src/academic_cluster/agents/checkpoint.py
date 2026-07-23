"""Lifecycle-managed PostgreSQL checkpoint storage for the Agent graph."""

from __future__ import annotations

import asyncio
import contextlib
from importlib.resources import files
from pathlib import Path
from typing import Any

import structlog
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

logger = structlog.get_logger()

_pool: AsyncConnectionPool[Any] | None = None
_checkpointer: AsyncPostgresSaver | None = None
_runtime_lock_connection: AsyncConnection[Any] | None = None
_runtime_lock_monitor: asyncio.Task[None] | None = None
_runtime_lock_lost = False
_init_lock = asyncio.Lock()
_runtime_lock_health_lock = asyncio.Lock()
_RUNTIME_LOCK_NAME = "academic-cluster:agent-runtime-singleton:v1"
_RUNTIME_LOCK_POLL_SECONDS = 5.0


def _source_migration_path() -> Path:
    return Path(__file__).resolve().parents[3] / "scripts" / "migrate_agent_tables.sql"


def _read_agent_schema_sql() -> str:
    """Load the migration from the wheel resource or the source checkout."""

    packaged = files("academic_cluster").joinpath("sql", "migrate_agent_tables.sql")
    if packaged.is_file():
        return packaged.read_text(encoding="utf-8")

    source_path = _source_migration_path()
    if source_path.is_file():
        return source_path.read_text(encoding="utf-8")
    raise RuntimeError(
        "Agent schema migration is missing from both the package and source tree: "
        f"{source_path}"
    )


async def _apply_agent_schema(pool: AsyncConnectionPool[Any]) -> None:
    sql = _read_agent_schema_sql()
    async with pool.connection() as connection, connection.cursor() as cursor:
        await cursor.execute(sql, prepare=False)


async def _acquire_runtime_lock(
    pool: AsyncConnectionPool[Any],
) -> AsyncConnection[Any]:
    """Hold one PostgreSQL session lock for the complete API lifetime."""

    connection: AsyncConnection[Any] = await pool.getconn()
    try:
        cursor = await connection.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS acquired",
            (_RUNTIME_LOCK_NAME,),
        )
        row = await cursor.fetchone()
        acquired = bool(row and row["acquired"])
        if not acquired:
            raise RuntimeError(
                "Another Academic Cluster API instance already owns the Agent "
                "runtime lock; configure exactly one application worker"
            )
        return connection
    except BaseException:
        await pool.putconn(connection)
        raise


async def _release_runtime_lock(
    pool: AsyncConnectionPool[Any],
    connection: AsyncConnection[Any],
) -> None:
    """Release and return the dedicated singleton-lock connection."""

    try:
        await connection.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
            (_RUNTIME_LOCK_NAME,),
        )
    finally:
        await pool.putconn(connection)


async def _handle_runtime_lock_loss(error: BaseException) -> None:
    """Fence this process and drain tasks after its singleton session is lost."""

    global _runtime_lock_lost
    if _runtime_lock_lost:
        return
    _runtime_lock_lost = True
    logger.critical(
        "Agent runtime singleton lock connection was lost; fencing process",
        error=str(error),
    )
    from ..services.agent_runtime import get_agent_run_manager

    await get_agent_run_manager().shutdown()


async def check_runtime_lock_health() -> bool:
    """Ping the dedicated advisory-lock session and fence failures."""

    connection = _runtime_lock_connection
    if _checkpointer is None or connection is None or _runtime_lock_lost:
        return False
    if connection.closed:
        await _handle_runtime_lock_loss(
            RuntimeError("runtime lock connection is already closed")
        )
        return False
    async with _runtime_lock_health_lock:
        try:
            await connection.execute("SELECT 1")
        except Exception as error:
            await _handle_runtime_lock_loss(error)
            return False
    return True


async def _monitor_runtime_lock() -> None:
    """Continuously detect a dropped PostgreSQL advisory-lock session."""

    try:
        while True:
            await asyncio.sleep(_RUNTIME_LOCK_POLL_SECONDS)
            if not await check_runtime_lock_health():
                return
    except asyncio.CancelledError:
        raise


def build_checkpoint_conninfo(settings: Any) -> str:
    """Build a libpq connection string without SQLAlchemy driver syntax."""

    return make_conninfo(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        application_name="academic-cluster-checkpoint",
        connect_timeout=10,
    )


async def initialize_checkpointer(
    settings: Any | None = None,
) -> BaseCheckpointSaver[Any]:
    """Open the pool, migrate saver tables, and compile the graph once."""

    global _checkpointer, _pool, _runtime_lock_connection
    global _runtime_lock_lost, _runtime_lock_monitor
    async with _init_lock:
        if _checkpointer is not None:
            if await check_runtime_lock_health():
                return _checkpointer
            raise RuntimeError("Agent runtime lock connection is no longer healthy")
        if settings is None:
            from ..config import get_settings

            settings = get_settings()

        pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
            conninfo=build_checkpoint_conninfo(settings),
            min_size=1,
            max_size=5,
            open=False,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
            check=AsyncConnectionPool.check_connection,
        )
        await pool.open(wait=True, timeout=30)
        runtime_lock_connection: AsyncConnection[Any] | None = None
        saver = AsyncPostgresSaver(pool)
        try:
            runtime_lock_connection = await _acquire_runtime_lock(pool)
            async with pool.connection() as connection:
                await connection.execute(
                    "SELECT pg_advisory_lock(hashtext("
                    "'academic-cluster:langgraph-checkpoint-setup'))"
                )
                try:
                    await _apply_agent_schema(pool)
                    await saver.setup()
                finally:
                    await connection.execute(
                        "SELECT pg_advisory_unlock(hashtext("
                        "'academic-cluster:langgraph-checkpoint-setup'))"
                    )
            from .agent_graph import compile_agent_graph

            await compile_agent_graph(saver, force=True)
        except BaseException:
            if runtime_lock_connection is not None:
                with contextlib.suppress(Exception):
                    await _release_runtime_lock(pool, runtime_lock_connection)
            await pool.close()
            raise

        _pool = pool
        _checkpointer = saver
        _runtime_lock_connection = runtime_lock_connection
        _runtime_lock_lost = False
        _runtime_lock_monitor = asyncio.create_task(
            _monitor_runtime_lock(), name="agent-runtime-lock-monitor"
        )
        logger.info("PostgreSQL Agent checkpointer initialized")
        return saver


async def close_checkpointer() -> None:
    """Release graph references before closing the psycopg pool."""

    global _checkpointer, _pool, _runtime_lock_connection
    global _runtime_lock_lost, _runtime_lock_monitor
    async with _init_lock:
        from .agent_graph import reset_agent_graph

        await reset_agent_graph()
        monitor = _runtime_lock_monitor
        _runtime_lock_monitor = None
        if monitor is not None and monitor is not asyncio.current_task():
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor
        release_error: Exception | None = None
        if _pool is not None and _runtime_lock_connection is not None:
            if _runtime_lock_lost or _runtime_lock_connection.closed:
                # PostgreSQL advisory locks are session scoped.  Once the
                # health check has fenced this process, closing/discarding the
                # failed session is both sufficient and safer than issuing an
                # unlock query on a broken connection.
                with contextlib.suppress(Exception):
                    await _runtime_lock_connection.close()
                with contextlib.suppress(Exception):
                    await _pool.putconn(_runtime_lock_connection)
            else:
                try:
                    await _release_runtime_lock(_pool, _runtime_lock_connection)
                except Exception as error:
                    release_error = error
                    logger.exception("Failed to release Agent runtime lock")
        _runtime_lock_connection = None
        if _pool is not None:
            await _pool.close()
        _pool = None
        _checkpointer = None
        _runtime_lock_lost = False
        logger.info("PostgreSQL Agent checkpointer closed")
        if release_error is not None:
            raise RuntimeError(
                "Failed to release Agent runtime lock"
            ) from release_error


def is_checkpointer_initialized() -> bool:
    """Return whether production checkpoint storage is ready."""

    connection = _runtime_lock_connection
    return bool(
        _checkpointer is not None
        and connection is not None
        and not _runtime_lock_lost
        and not connection.closed
    )


async def delete_project_checkpoints(project_id: str) -> int:
    """Delete every LangGraph checkpoint thread owned by a project."""

    if _pool is None or _checkpointer is None:
        return 0

    from .agent_graph import agent_thread_prefix

    prefix = agent_thread_prefix(project_id)
    thread_pattern = f"{prefix}%"
    async with _pool.connection() as connection:
        cursor = await connection.execute(
            """
            SELECT DISTINCT thread_id
            FROM (
                SELECT thread_id FROM checkpoints WHERE thread_id LIKE %s
                UNION ALL
                SELECT thread_id FROM checkpoint_blobs WHERE thread_id LIKE %s
                UNION ALL
                SELECT thread_id FROM checkpoint_writes WHERE thread_id LIKE %s
            ) AS project_threads
            """,
            (thread_pattern, thread_pattern, thread_pattern),
        )
        rows = await cursor.fetchall()

    thread_ids = [str(row["thread_id"]) for row in rows]
    for thread_id in thread_ids:
        await _checkpointer.adelete_thread(thread_id)
    if thread_ids:
        logger.info(
            "Deleted project Agent checkpoints",
            project_id=project_id,
            thread_count=len(thread_ids),
        )
    return len(thread_ids)
