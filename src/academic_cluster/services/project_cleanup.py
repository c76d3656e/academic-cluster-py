"""Coordinated project deletion across tasks, checkpoints, and SQL data."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import text

logger = structlog.get_logger()


async def delete_project_data(project_id: str, db: Any) -> None:
    """Stop the project, erase checkpoint payloads, then delete scoped rows."""

    from ..agents.checkpoint import delete_project_checkpoints
    from .agent_runtime import get_agent_run_manager

    manager = get_agent_run_manager()
    await manager.begin_project_deletion(project_id)
    try:
        await delete_project_checkpoints(project_id)
        params = {"project_id": project_id}
        async with db.session() as session:
            # LLM calls have nullable legacy foreign keys, so delete every
            # attribution path before removing executions and pipeline runs.
            await session.execute(
                text("""
                    DELETE FROM llm_calls
                    WHERE project_id = :project_id
                       OR execution_id IN (
                           SELECT id FROM agent_executions
                           WHERE project_id = :project_id
                       )
                       OR pipeline_run_id IN (
                           SELECT id FROM pipeline_runs
                           WHERE project_id = :project_id
                       )
                """),
                params,
            )
            await session.execute(
                text("""
                    DELETE FROM written_content
                    WHERE outline_id IN (
                        SELECT id FROM outlines WHERE project_id = :project_id
                    )
                """),
                params,
            )
            await session.execute(
                text("""
                    DELETE FROM cluster_assignments
                    WHERE cluster_id IN (
                        SELECT id FROM clusters WHERE project_id = :project_id
                    )
                """),
                params,
            )
            for table_name in (
                "agent_tool_calls",
                "agent_decisions",
                "project_papers",
                "agent_executions",
                "evidence_cards",
                "outlines",
                "clusters",
                "pipeline_audit_log",
                "pipeline_checkpoints",
                "pipeline_runs",
            ):
                await session.execute(
                    text(f"DELETE FROM {table_name} WHERE project_id = :project_id"),  # nosec B608
                    params,
                )
            await session.execute(
                text("DELETE FROM projects WHERE id = :project_id"),
                params,
            )
    finally:
        await manager.end_project_deletion(project_id)

    logger.info("Deleted project runtime and persisted data", project_id=project_id)
