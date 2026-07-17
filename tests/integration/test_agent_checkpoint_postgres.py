"""Cross-connection recovery tests for LangGraph PostgreSQL checkpoints."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any, TypedDict

import pytest
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from psycopg import AsyncConnection, sql
from sqlalchemy.engine import make_url

from academic_cluster.agents.agent_graph import agent_thread_id
from academic_cluster.agents.checkpoint import (
    _RUNTIME_LOCK_NAME,
    _read_agent_schema_sql,
    check_runtime_lock_health,
    close_checkpointer,
    delete_project_checkpoints,
    initialize_checkpointer,
    is_checkpointer_initialized,
)
from academic_cluster.services.agent_runtime import (
    close_agent_run_manager,
    get_agent_run_manager,
)

pytestmark = pytest.mark.integration


class _RestartState(TypedDict, total=False):
    topic: str
    approval: str
    result: str


def _build_restart_graph(checkpointer: BaseCheckpointSaver[Any]) -> Any:
    def request_approval(state: _RestartState) -> dict[str, str]:
        approval = interrupt({"topic": state["topic"], "action": "approve"})
        return {"approval": str(approval)}

    def finalize(state: _RestartState) -> dict[str, str]:
        return {"result": f"restored:{state['topic']}:{state['approval']}"}

    graph = StateGraph(_RestartState)
    graph.add_node("request_approval", request_approval)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "request_approval")
    graph.add_edge("request_approval", "finalize")
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def _psycopg_url(asyncpg_url: str) -> str:
    return asyncpg_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _checkpoint_settings(asyncpg_url: str) -> SimpleNamespace:
    url = make_url(asyncpg_url)
    return SimpleNamespace(
        postgres_host=url.host,
        postgres_port=url.port,
        postgres_db=url.database,
        postgres_user=url.username,
        postgres_password=url.password,
    )


async def _thread_row_count(
    connection: AsyncConnection[Any],
    table_name: str,
    thread_id: str,
) -> int:
    cursor = await connection.execute(
        sql.SQL("SELECT COUNT(*) FROM {} WHERE thread_id = %s").format(
            sql.Identifier(table_name)
        ),
        (thread_id,),
    )
    row = await cursor.fetchone()
    assert row is not None
    return int(row[0])


async def _wait_forever() -> None:
    await asyncio.Event().wait()


async def test_runtime_checkpointer_can_close_and_reopen(
    agent_postgres_url: str,
) -> None:
    """The application lifecycle runs migrations and replaces a closed pool."""

    settings = _checkpoint_settings(agent_postgres_url)

    try:
        first_saver = await initialize_checkpointer(settings)
        assert is_checkpointer_initialized()
        await close_checkpointer()
        assert not is_checkpointer_initialized()

        second_saver = await initialize_checkpointer(settings)
        assert is_checkpointer_initialized()
        assert second_saver is not first_saver
    finally:
        await close_checkpointer()


async def test_runtime_lock_rejects_a_second_application_instance(
    agent_postgres_url: str,
) -> None:
    """One database permits exactly one process-local Agent task owner."""

    connection = await AsyncConnection.connect(_psycopg_url(agent_postgres_url))
    try:
        await initialize_checkpointer(_checkpoint_settings(agent_postgres_url))
        cursor = await connection.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
            (_RUNTIME_LOCK_NAME,),
        )
        assert await cursor.fetchone() == (False,)
    finally:
        await close_checkpointer()

    try:
        cursor = await connection.execute(
            "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
            (_RUNTIME_LOCK_NAME,),
        )
        assert await cursor.fetchone() == (True,)
        await connection.execute(
            "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
            (_RUNTIME_LOCK_NAME,),
        )
    finally:
        await connection.close()


async def test_checkpoint_resumes_after_first_saver_is_closed(
    agent_postgres_url: str,
) -> None:
    """A second saver restores and completes an interrupt from the first saver."""

    checkpoint_url = _psycopg_url(agent_postgres_url)
    thread_id = f"integration:checkpoint:{uuid.uuid4()}"
    config = {
        "configurable": {"thread_id": thread_id, "checkpoint_ns": ""},
        "recursion_limit": 10,
    }

    async with AsyncPostgresSaver.from_conn_string(checkpoint_url) as saver_one:
        await saver_one.setup()
        graph_one = _build_restart_graph(saver_one)
        paused = await graph_one.ainvoke({"topic": "durable-agent"}, config)
        assert paused["topic"] == "durable-agent"
        assert paused["__interrupt__"]
        snapshot_one = await graph_one.aget_state(config)
        assert snapshot_one.values["topic"] == "durable-agent"
        assert snapshot_one.next == ("request_approval",)

    async with AsyncPostgresSaver.from_conn_string(checkpoint_url) as saver_two:
        graph_two = _build_restart_graph(saver_two)
        snapshot_two = await graph_two.aget_state(config)
        assert snapshot_two.values["topic"] == "durable-agent"
        assert snapshot_two.next == ("request_approval",)

        completed = await graph_two.ainvoke(Command(resume="yes"), config)
        assert completed["approval"] == "yes"
        assert completed["result"] == "restored:durable-agent:yes"
        final_snapshot = await graph_two.aget_state(config)
        assert final_snapshot.next == ()
        assert final_snapshot.values["result"] == "restored:durable-agent:yes"


async def test_project_checkpoint_deletion_clears_all_langgraph_tables(
    agent_postgres_url: str,
) -> None:
    """Project cleanup removes checkpoints, blobs, and pending writes."""

    project_id = str(uuid.uuid4())
    execution_id = str(uuid.uuid4())
    thread_id = agent_thread_id(project_id, execution_id)
    config = {
        "configurable": {"thread_id": thread_id, "checkpoint_ns": ""},
        "recursion_limit": 10,
    }
    connection = await AsyncConnection.connect(_psycopg_url(agent_postgres_url))

    try:
        saver = await initialize_checkpointer(_checkpoint_settings(agent_postgres_url))
        graph = _build_restart_graph(saver)
        paused = await graph.ainvoke({"topic": "delete-all-checkpoint-data"}, config)
        assert paused["__interrupt__"]

        counts_before: dict[str, int] = {}
        for table_name in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            counts_before[table_name] = await _thread_row_count(
                connection,
                table_name,
                thread_id,
            )

        assert all(count > 0 for count in counts_before.values())
        assert await delete_project_checkpoints(project_id) == 1

        for table_name in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            assert await _thread_row_count(connection, table_name, thread_id) == 0
    finally:
        await connection.close()
        await close_checkpointer()


async def test_project_checkpoint_deletion_removes_orphan_blobs_and_writes(
    agent_postgres_url: str,
) -> None:
    """Cleanup discovers threads even when their main checkpoint row is gone."""

    project_id = str(uuid.uuid4())
    execution_id = str(uuid.uuid4())
    thread_id = agent_thread_id(project_id, execution_id)
    config = {
        "configurable": {"thread_id": thread_id, "checkpoint_ns": ""},
        "recursion_limit": 10,
    }
    connection = await AsyncConnection.connect(
        _psycopg_url(agent_postgres_url),
        autocommit=True,
    )

    try:
        saver = await initialize_checkpointer(_checkpoint_settings(agent_postgres_url))
        graph = _build_restart_graph(saver)
        paused = await graph.ainvoke({"topic": "orphan-checkpoint-data"}, config)
        assert paused["__interrupt__"]

        await connection.execute(
            "DELETE FROM checkpoints WHERE thread_id = %s",
            (thread_id,),
        )
        for table_name in ("checkpoint_blobs", "checkpoint_writes"):
            assert await _thread_row_count(connection, table_name, thread_id) > 0

        assert await delete_project_checkpoints(project_id) == 1

        for table_name in ("checkpoint_blobs", "checkpoint_writes"):
            assert await _thread_row_count(connection, table_name, thread_id) == 0
    finally:
        for table_name in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            await connection.execute(
                sql.SQL("DELETE FROM {} WHERE thread_id = %s").format(
                    sql.Identifier(table_name)
                ),
                (thread_id,),
            )
        await connection.close()
        await close_checkpointer()


async def test_runtime_lock_backend_loss_fences_the_live_manager(
    agent_postgres_url: str,
) -> None:
    """A terminated lock session cancels work and prevents new Agent starts."""

    control_connection = await AsyncConnection.connect(
        _psycopg_url(agent_postgres_url),
        autocommit=True,
    )
    manager = get_agent_run_manager()
    blocker = asyncio.create_task(_wait_forever())
    manager._tasks["fencing-integration"] = blocker

    try:
        await initialize_checkpointer(_checkpoint_settings(agent_postgres_url))
        from academic_cluster.agents import checkpoint

        lock_connection = checkpoint._runtime_lock_connection
        assert lock_connection is not None
        cursor = await lock_connection.execute("SELECT pg_backend_pid() AS pid")
        lock_backend = await cursor.fetchone()
        assert lock_backend is not None
        terminated = await control_connection.execute(
            "SELECT pg_terminate_backend(%s)",
            (lock_backend["pid"],),
        )
        assert await terminated.fetchone() == (True,)

        assert not await check_runtime_lock_health()
        assert not is_checkpointer_initialized()
        assert blocker.cancelled()
        assert not manager._accepting
    finally:
        await control_connection.close()
        try:
            await close_checkpointer()
        finally:
            await close_agent_run_manager()


async def test_legacy_agent_schema_is_mapped_and_migration_is_idempotent(
    agent_postgres_url: str,
) -> None:
    """Prototype column names and populated rows survive an in-place upgrade."""

    schema_name = f"legacy_agent_{uuid.uuid4().hex}"
    connection = await AsyncConnection.connect(
        _psycopg_url(agent_postgres_url),
        autocommit=True,
    )
    try:
        await connection.execute(
            sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name))
        )
        await connection.execute(
            sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name))
        )
        await connection.execute("""
            CREATE TABLE projects (
                id UUID PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                status VARCHAR(50) DEFAULT 'created'
            );
            CREATE TABLE papers (id UUID PRIMARY KEY);
            CREATE TABLE pipeline_runs (
                id UUID PRIMARY KEY,
                project_id UUID NOT NULL REFERENCES projects(id)
            );
            CREATE TABLE llm_calls (
                id UUID PRIMARY KEY,
                pipeline_run_id UUID REFERENCES pipeline_runs(id)
            );
            CREATE TABLE agent_executions (
                id UUID PRIMARY KEY,
                pipeline_run_id UUID REFERENCES pipeline_runs(id),
                agent_name VARCHAR(100),
                agent_type VARCHAR(50),
                input_state JSONB,
                output_state JSONB,
                duration_ms INTEGER,
                token_usage JSONB,
                quality_score DOUBLE PRECISION,
                started_at TIMESTAMP,
                finished_at TIMESTAMP
            );
            CREATE TABLE agent_decisions (
                id UUID PRIMARY KEY,
                agent_execution_id UUID REFERENCES agent_executions(id),
                decision_type VARCHAR(100),
                decision_data JSONB,
                reason TEXT,
                created_at TIMESTAMP
            );
            CREATE TABLE agent_tool_calls (
                id UUID PRIMARY KEY,
                agent_execution_id UUID REFERENCES agent_executions(id),
                tool_name VARCHAR(100),
                input_data JSONB,
                output_data JSONB,
                duration_ms INTEGER,
                status VARCHAR(20),
                error_message TEXT,
                created_at TIMESTAMP
            );
        """)

        project_id = uuid.uuid4()
        run_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        decision_id = uuid.uuid4()
        tool_call_id = uuid.uuid4()
        await connection.execute(
            "INSERT INTO projects (id, name) VALUES (%s, 'legacy project')",
            (project_id,),
        )
        await connection.execute(
            "INSERT INTO pipeline_runs (id, project_id) VALUES (%s, %s)",
            (run_id, project_id),
        )
        await connection.execute(
            """
            INSERT INTO agent_executions (
                id, pipeline_run_id, agent_name, agent_type, input_state,
                output_state, duration_ms, token_usage, quality_score,
                started_at, finished_at
            ) VALUES (
                %s, %s, NULL, 'research', '{"topic":"legacy"}',
                '{"papers":2}', 17, '{"total":9}', 81.5,
                CURRENT_TIMESTAMP - INTERVAL '1 minute', CURRENT_TIMESTAMP
            )
            """,
            (execution_id, run_id),
        )
        await connection.execute(
            """
            INSERT INTO agent_decisions (
                id, agent_execution_id, decision_type, decision_data, reason
            ) VALUES (
                %s, %s, 'continue_to_analysis', '{"coverage":0.8}', 'enough papers'
            )
            """,
            (decision_id, execution_id),
        )
        await connection.execute(
            """
            INSERT INTO agent_tool_calls (
                id, agent_execution_id, tool_name, input_data, output_data,
                duration_ms, status
            ) VALUES (
                %s, %s, 'search_papers', '{"query":"legacy"}',
                '{"papers":2}', 11, 'success'
            )
            """,
            (tool_call_id, execution_id),
        )

        migration_sql = _read_agent_schema_sql()
        await connection.execute(migration_sql, prepare=False)
        await connection.execute(migration_sql, prepare=False)

        execution_cursor = await connection.execute(
            """
            SELECT project_id, agent_name, status, input_state, output_state
            FROM agent_executions WHERE id = %s
            """,
            (execution_id,),
        )
        execution = await execution_cursor.fetchone()
        decision_cursor = await connection.execute(
            """
            SELECT execution_id, project_id, agent_name, decision
            FROM agent_decisions WHERE id = %s
            """,
            (decision_id,),
        )
        decision = await decision_cursor.fetchone()
        tool_call_cursor = await connection.execute(
            """
            SELECT execution_id, project_id, agent_name,
                   input_summary, output_summary
            FROM agent_tool_calls WHERE id = %s
            """,
            (tool_call_id,),
        )
        tool_call = await tool_call_cursor.fetchone()

        assert execution == (
            project_id,
            "research",
            "succeeded",
            {"topic": "legacy"},
            {"papers": 2},
        )
        assert decision == (
            execution_id,
            project_id,
            "research",
            "continue_to_analysis",
        )
        assert tool_call == (
            execution_id,
            project_id,
            "research",
            '{"query": "legacy"}',
            '{"papers": 2}',
        )
    finally:
        await connection.execute("SET search_path TO public")
        await connection.execute(
            sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                sql.Identifier(schema_name)
            )
        )
        await connection.close()
