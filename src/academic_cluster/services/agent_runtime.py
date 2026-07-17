"""Single runtime manager shared by every Agent API alias."""

from __future__ import annotations

import asyncio
import contextlib
import enum
import math
import uuid
from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

logger = structlog.get_logger()

DEFAULT_QUALITY_THRESHOLD = 75.0
DEFAULT_TARGET_PAPERS = 50
DEFAULT_TARGET_WORDS = 12000


def _resolve_quality_threshold(config: Any) -> float:
    """Parse legacy project JSON into the AgentState quality range."""

    if not isinstance(config, dict):
        return DEFAULT_QUALITY_THRESHOLD
    raw_threshold = config.get("quality_threshold", DEFAULT_QUALITY_THRESHOLD)
    if isinstance(raw_threshold, bool):
        return DEFAULT_QUALITY_THRESHOLD
    try:
        threshold = float(raw_threshold)
    except (TypeError, ValueError):
        return DEFAULT_QUALITY_THRESHOLD
    if not math.isfinite(threshold):
        return DEFAULT_QUALITY_THRESHOLD
    return max(0.0, min(threshold, 100.0))


def _bounded_execution_int(
    value: Any,
    *,
    fallback: int,
    minimum: int,
    maximum: int,
) -> int:
    """Read a prior execution input without trusting legacy JSON types."""

    if isinstance(value, bool):
        parsed = fallback
    else:
        try:
            parsed = int(value)
        except (TypeError, ValueError, OverflowError):
            parsed = fallback
    return max(minimum, min(parsed, maximum))


def resolve_agent_targets(config: Any) -> tuple[int, int]:
    """Return finite, bounded execution targets from untrusted project JSON."""

    values = config if isinstance(config, dict) else {}
    return (
        _bounded_execution_int(
            values.get("target_papers"),
            fallback=DEFAULT_TARGET_PAPERS,
            minimum=1,
            maximum=500,
        ),
        _bounded_execution_int(
            values.get("target_words"),
            fallback=DEFAULT_TARGET_WORDS,
            minimum=1000,
            maximum=100000,
        ),
    )


class AgentAlreadyRunningError(RuntimeError):
    """Raised when a project already has an active execution."""


class AgentNotRunningError(RuntimeError):
    """Raised when cancellation targets an idle project."""


class AgentCheckpointNotFoundError(RuntimeError):
    """Raised when no interrupted execution can be resumed."""


class AgentRuntimeUnavailableError(RuntimeError):
    """Raised when the application runtime can no longer accept work."""


class CheckpointDisposition(enum.StrEnum):
    """Resume action derived from the persisted graph snapshot."""

    MISSING = "missing"
    RUNNABLE = "runnable"
    TERMINAL_SUCCESS = "terminal_success"
    TERMINAL_FAILURE = "terminal_failure"
    TERMINAL_UNKNOWN = "terminal_unknown"


@dataclass(frozen=True)
class CheckpointInspection:
    """Validated checkpoint classification and its persisted state values."""

    disposition: CheckpointDisposition
    values: dict[str, Any]


async def _inspect_checkpoint(
    project_id: str, execution_id: str
) -> CheckpointInspection:
    """Classify a checkpoint by runnable nodes and terminal graph state."""

    from ..agents.agent_graph import _thread_config, compile_agent_graph

    graph = await compile_agent_graph()
    snapshot = await graph.aget_state(_thread_config(project_id, execution_id))
    values = dict(snapshot.values or {})
    if not values:
        return CheckpointInspection(CheckpointDisposition.MISSING, {})
    if snapshot.next:
        return CheckpointInspection(CheckpointDisposition.RUNNABLE, values)

    status = str(values.get("status") or "")
    errors = values.get("errors") or []
    if status in {"completed", "completed_with_warnings"} and not errors:
        disposition = CheckpointDisposition.TERMINAL_SUCCESS
    elif status == "failed" or values.get("terminal_failure") or errors:
        disposition = CheckpointDisposition.TERMINAL_FAILURE
    else:
        disposition = CheckpointDisposition.TERMINAL_UNKNOWN
    return CheckpointInspection(disposition, values)


async def _claim_resumable_execution(
    db: Any,
    *,
    project_id: str,
    execution_id: str,
) -> bool:
    """Atomically move one checkpoint-runnable execution back to pending.

    The status predicate prevents two application workers from resuming the
    same checkpoint concurrently.
    """

    async with db.session() as session:
        result = await session.execute(
            text("""
                UPDATE agent_executions
                SET status = 'pending',
                    finished_at = NULL,
                    error_message = NULL
                WHERE id = :execution_id
                  AND project_id = :project_id
                  AND status IN ('interrupted', 'failed')
                RETURNING id
            """),
            {
                "execution_id": execution_id,
                "project_id": project_id,
            },
        )
        return result.fetchone() is not None


class AgentRunManager:
    """Own process-local tasks while PostgreSQL enforces global uniqueness."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._deleting_projects: set[str] = set()
        self._lock = asyncio.Lock()
        self._accepting = True

    async def start(
        self,
        *,
        project: dict[str, Any],
        target_papers: int,
        target_words: int,
        sse_manager: Any = None,
        resume: bool = False,
        db: Any | None = None,
    ) -> str:
        """Persist a pending execution before scheduling background work."""

        from ..agents.checkpoint import (
            check_runtime_lock_health,
            is_checkpointer_initialized,
        )

        if not self._accepting:
            raise AgentRuntimeUnavailableError("Agent runtime is shutting down")
        if not is_checkpointer_initialized():
            raise AgentRuntimeUnavailableError(
                "Persistent Agent checkpointer is not initialized"
            )
        if not await check_runtime_lock_health():
            raise AgentRuntimeUnavailableError(
                "Persistent Agent runtime lock is unavailable"
            )

        project_id = str(project["id"])
        topic = str(project.get("query") or "")
        project_config = project.get("config") or {}
        quality_threshold = _resolve_quality_threshold(project_config)
        target_papers, target_words = resolve_agent_targets(
            {
                "target_papers": target_papers,
                "target_words": target_words,
            }
        )
        if db is None:
            from .database import get_database

            db = get_database()
        async with self._lock:
            if not self._accepting:
                raise AgentRuntimeUnavailableError("Agent runtime is shutting down")
            if project_id in self._deleting_projects:
                raise AgentRuntimeUnavailableError(
                    f"Project {project_id} is being deleted"
                )
            task = self._tasks.get(project_id)
            if task is not None and not task.done():
                raise AgentAlreadyRunningError(
                    f"Agent already running for project {project_id}"
                )

            resume_from_checkpoint = False
            retry_of_execution_id: str | None = None
            if resume:
                execution = await db.get_latest_agent_execution(project_id)
                if execution and execution.get("status") in {"pending", "running"}:
                    raise AgentAlreadyRunningError(
                        f"Agent already running for project {project_id}"
                    )
                if not execution or execution.get("status") not in {
                    "interrupted",
                    "failed",
                }:
                    raise AgentCheckpointNotFoundError(
                        f"No resumable execution found for project {project_id}"
                    )
                previous_execution_id = str(execution["id"])
                inspection = await _inspect_checkpoint(
                    project_id, previous_execution_id
                )
                if inspection.disposition is CheckpointDisposition.RUNNABLE:
                    try:
                        claimed = await _claim_resumable_execution(
                            db,
                            project_id=project_id,
                            execution_id=previous_execution_id,
                        )
                    except IntegrityError as error:
                        raise AgentAlreadyRunningError(
                            f"Agent already running for project {project_id}"
                        ) from error
                    if not claimed:
                        raise AgentAlreadyRunningError(
                            f"Agent already running for project {project_id}"
                        )
                    execution_id = previous_execution_id
                    resume_from_checkpoint = True
                elif inspection.disposition is CheckpointDisposition.TERMINAL_SUCCESS:
                    values = inspection.values
                    await db.update_agent_execution(
                        previous_execution_id,
                        "succeeded",
                        output_state={
                            "status": values.get("status"),
                            "warnings": values.get("warnings") or [],
                            "errors": [],
                        },
                        quality_score=values.get("quality_score"),
                    )
                    await db.update_project_status(project_id, "completed")
                    return previous_execution_id
                elif (
                    inspection.disposition is CheckpointDisposition.TERMINAL_FAILURE
                    or (
                        inspection.disposition is CheckpointDisposition.MISSING
                        and execution.get("status") == "failed"
                    )
                ):
                    retry_of_execution_id = previous_execution_id
                    prior_input = execution.get("input_state")
                    if isinstance(prior_input, dict):
                        prior_topic = str(prior_input.get("topic") or "").strip()
                        if prior_topic:
                            topic = prior_topic
                        target_papers = _bounded_execution_int(
                            prior_input.get("target_papers"),
                            fallback=target_papers,
                            minimum=1,
                            maximum=500,
                        )
                        target_words = _bounded_execution_int(
                            prior_input.get("target_words"),
                            fallback=target_words,
                            minimum=1000,
                            maximum=100000,
                        )
                        quality_threshold = _resolve_quality_threshold(prior_input)
                elif inspection.disposition is CheckpointDisposition.MISSING:
                    raise AgentCheckpointNotFoundError(
                        "Interrupted execution has no checkpoint: "
                        f"{previous_execution_id}"
                    )
                else:
                    raise AgentCheckpointNotFoundError(
                        "Execution checkpoint reached END without a terminal status: "
                        f"{previous_execution_id}"
                    )

            if not resume_from_checkpoint:
                execution_id = str(uuid.uuid4())
                try:
                    await db.create_agent_execution(
                        execution_id=execution_id,
                        project_id=project_id,
                        input_state={
                            "topic": topic,
                            "target_papers": target_papers,
                            "target_words": target_words,
                            "quality_threshold": quality_threshold,
                            "retry_of_execution_id": retry_of_execution_id,
                        },
                    )
                except IntegrityError as error:
                    raise AgentAlreadyRunningError(
                        f"Agent already running for project {project_id}"
                    ) from error

            # Make the accepted state visible before returning to callers.
            # The execution row remains the source of truth if this best-effort
            # project status update is temporarily unavailable.
            try:
                await db.update_project_status(
                    project_id,
                    "running:agent:supervisor",
                )
            except Exception as error:
                logger.warning(
                    "Failed to publish accepted Agent status",
                    project_id=project_id,
                    execution_id=execution_id,
                    error=str(error),
                )

            # Lock-loss fencing can start while the database calls above are
            # awaiting. Never schedule new work after shutdown has begun.
            if not self._accepting:
                with contextlib.suppress(Exception):
                    await db.update_agent_execution(
                        execution_id,
                        "interrupted",
                        error_message="Agent runtime stopped before scheduling",
                    )
                with contextlib.suppress(Exception):
                    await db.update_project_status(project_id, "interrupted")
                raise AgentRuntimeUnavailableError(
                    "Agent runtime stopped before execution could be scheduled"
                )

            background = asyncio.create_task(
                self._run(
                    project=project,
                    topic=topic,
                    execution_id=execution_id,
                    target_papers=target_papers,
                    target_words=target_words,
                    quality_threshold=quality_threshold,
                    sse_manager=sse_manager,
                    resume=resume_from_checkpoint,
                    db=db,
                ),
                name=f"agent:{project_id}:{execution_id}",
            )
            self._tasks[project_id] = background
            return execution_id

    async def _run(
        self,
        *,
        project: dict[str, Any],
        topic: str | None = None,
        execution_id: str,
        target_papers: int,
        target_words: int,
        quality_threshold: float | None = None,
        sse_manager: Any,
        resume: bool,
        db: Any,
    ) -> None:
        from ..agents.orchestrator import create_orchestrator

        project_id = str(project["id"])
        try:
            await db.update_agent_execution(execution_id, "running")
            orchestrator = create_orchestrator(
                quality_threshold=(
                    _resolve_quality_threshold(project.get("config") or {})
                    if quality_threshold is None
                    else quality_threshold
                ),
            )
            result = await orchestrator.run(
                topic=(str(project.get("query") or "") if topic is None else topic),
                project_id=project_id,
                execution_id=execution_id,
                target_papers=target_papers,
                target_words=target_words,
                resume=resume,
                sse_manager=sse_manager,
            )
            succeeded = result.get("status") != "failed" and not result.get("errors")
            await db.update_agent_execution(
                execution_id,
                "succeeded" if succeeded else "failed",
                output_state={
                    "status": result.get("status"),
                    "warnings": result.get("warnings") or [],
                    "errors": result.get("errors") or [],
                },
                quality_score=result.get("quality_score"),
                error_message=(
                    None
                    if succeeded
                    else "; ".join(result.get("errors") or ["Agent execution failed"])
                ),
            )
            await db.update_project_status(
                project_id,
                "completed" if succeeded else "failed",
            )
        except asyncio.CancelledError:
            try:
                await db.update_agent_execution(
                    execution_id,
                    "interrupted",
                    error_message="Execution cancelled by user or server shutdown",
                )
            except Exception as cleanup_error:
                logger.exception(
                    "Failed to persist Agent execution cancellation",
                    project_id=project_id,
                    execution_id=execution_id,
                    error=str(cleanup_error),
                )
            try:
                await db.update_project_status(project_id, "interrupted")
            except Exception as cleanup_error:
                logger.exception(
                    "Failed to persist project cancellation",
                    project_id=project_id,
                    execution_id=execution_id,
                    error=str(cleanup_error),
                )
            raise
        except Exception as error:
            logger.exception(
                "Agent background execution failed",
                project_id=project_id,
                execution_id=execution_id,
            )
            try:
                await db.update_agent_execution(
                    execution_id,
                    "failed",
                    error_message=str(error)[:2000],
                )
            except Exception as persist_error:
                logger.exception(
                    "Failed to persist Agent failure",
                    project_id=project_id,
                    execution_id=execution_id,
                    error=str(persist_error),
                )
            try:
                await db.update_project_status(project_id, "failed")
            except Exception as persist_error:
                logger.exception(
                    "Failed to persist project failure",
                    project_id=project_id,
                    execution_id=execution_id,
                    error=str(persist_error),
                )
            if sse_manager is not None:
                with contextlib.suppress(Exception):
                    await sse_manager.send_error(project_id, str(error))
        finally:
            async with self._lock:
                current = self._tasks.get(project_id)
                if current is asyncio.current_task():
                    self._tasks.pop(project_id, None)

    async def cancel(self, project_id: str) -> None:
        """Cancel and await the complete task tree before returning."""

        async with self._lock:
            task = self._tasks.get(project_id)
            if task is None or task.done():
                raise AgentNotRunningError(
                    f"Agent is not running for project {project_id}"
                )
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def begin_project_deletion(self, project_id: str) -> None:
        """Block new starts, cancel an active task, and await its full tree."""

        async with self._lock:
            self._deleting_projects.add(project_id)
            task = self._tasks.get(project_id)
            if task is not None and not task.done():
                task.cancel()
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def end_project_deletion(self, project_id: str) -> None:
        """Release the temporary start barrier after deletion finishes."""

        async with self._lock:
            self._deleting_projects.discard(project_id)

    async def wait(self, project_id: str) -> None:
        """Wait for a task, primarily for controlled shutdown and tests."""

        async with self._lock:
            task = self._tasks.get(project_id)
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def shutdown(self) -> None:
        """Stop accepting work, cancel all runs, and await their cleanup."""

        self._accepting = False
        async with self._lock:
            tasks = list(self._tasks.values())
            for task in tasks:
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._lock:
            self._tasks.clear()
            self._deleting_projects.clear()

    def is_running(self, project_id: str) -> bool:
        task = self._tasks.get(project_id)
        return task is not None and not task.done()


_agent_run_manager: AgentRunManager | None = None


def get_agent_run_manager() -> AgentRunManager:
    global _agent_run_manager
    if _agent_run_manager is None:
        _agent_run_manager = AgentRunManager()
    return _agent_run_manager


async def close_agent_run_manager() -> None:
    global _agent_run_manager
    if _agent_run_manager is not None:
        await _agent_run_manager.shutdown()
        _agent_run_manager = None
