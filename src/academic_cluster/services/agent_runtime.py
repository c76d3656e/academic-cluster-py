"""Single runtime manager shared by every Agent API alias."""

from __future__ import annotations

import asyncio
import contextlib
import enum
import math
import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from .concurrency import (
    BoundedFifoGate,
    ConcurrencyQueueFullError,
    ConcurrencyQueueTimeoutError,
)

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


class AgentQueueFullError(AgentRuntimeUnavailableError):
    """Raised when the bounded Agent admission queue is full."""


class AgentCancellationTimeoutError(AgentRuntimeUnavailableError):
    """Raised when a cancelled provider tree misses the control-plane deadline."""


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


@dataclass
class _ScheduledExecution:
    """In-process metadata needed to make queued cancellation durable."""

    project_id: str
    execution_id: str
    db: Any
    started: bool = False
    interruption_persisted: bool = False
    persistence_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


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

    def __init__(
        self,
        *,
        max_concurrent_runs: int | None = None,
        max_queued_runs: int | None = None,
        max_admitted_runs_per_user: int | None = None,
        queue_wait_timeout_seconds: float | None = None,
        cancel_timeout_seconds: float | None = None,
    ) -> None:
        from ..config import get_settings

        settings = get_settings()
        self._max_concurrent_runs = (
            settings.agent_max_concurrent_runs
            if max_concurrent_runs is None
            else max_concurrent_runs
        )
        self._max_queued_runs = (
            settings.agent_max_queued_runs
            if max_queued_runs is None
            else max_queued_runs
        )
        self._max_admitted_runs_per_user = (
            settings.agent_max_admitted_runs_per_user
            if max_admitted_runs_per_user is None
            else max_admitted_runs_per_user
        )
        self._queue_wait_timeout_seconds = (
            settings.agent_queue_wait_timeout_seconds
            if queue_wait_timeout_seconds is None
            else queue_wait_timeout_seconds
        )
        self._cancel_timeout_seconds = (
            settings.agent_cancel_timeout_seconds
            if cancel_timeout_seconds is None
            else cancel_timeout_seconds
        )
        if self._max_concurrent_runs < 1:
            raise ValueError("max_concurrent_runs must be at least one")
        if self._max_queued_runs < 0:
            raise ValueError("max_queued_runs cannot be negative")
        if self._max_admitted_runs_per_user < 1:
            raise ValueError("max_admitted_runs_per_user must be at least one")
        if self._queue_wait_timeout_seconds <= 0:
            raise ValueError("queue_wait_timeout_seconds must be positive")
        if self._cancel_timeout_seconds <= 0:
            raise ValueError("cancel_timeout_seconds must be positive")
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._scheduled: dict[str, _ScheduledExecution] = {}
        self._starting_projects: set[str] = set()
        self._project_owners: dict[str, str] = {}
        self._deleting_projects: set[str] = set()
        self._run_gate = BoundedFifoGate(
            capacity=self._max_concurrent_runs,
            max_waiters=self._max_queued_runs,
        )
        self._lock = asyncio.Lock()
        self._accepting = True

    def _admission_is_full(self) -> bool:
        """Count starts in progress so concurrent HTTP requests cannot over-admit."""

        return (
            len(self._project_owners)
            >= self._max_concurrent_runs + self._max_queued_runs
        )

    def _owner_admission_is_full(self, owner_id: str) -> bool:
        return (
            sum(owner == owner_id for owner in self._project_owners.values())
            >= self._max_admitted_runs_per_user
        )

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

        if db is None:
            from .database import get_database

            db = get_database()

        project_id = str(project["id"])
        owner_id = str(project.get("user_id") or "anonymous")
        topic = str(project.get("query") or "")
        project_config = project.get("config") or {}
        from .runtime_policy import get_runtime_policy

        runtime_policy = await get_runtime_policy(db)
        if (
            not isinstance(project_config, dict)
            or "target_papers" not in project_config
        ):
            target_papers = runtime_policy.default_target_papers
        if not isinstance(project_config, dict) or "target_words" not in project_config:
            target_words = runtime_policy.default_target_words
        quality_threshold = (
            _resolve_quality_threshold(project_config)
            if isinstance(project_config, dict)
            and "quality_threshold" in project_config
            else runtime_policy.quality_threshold
        )
        target_papers, target_words = resolve_agent_targets(
            {
                "target_papers": target_papers,
                "target_words": target_words,
            }
        )
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
            if project_id in self._starting_projects:
                raise AgentAlreadyRunningError(
                    f"Agent already starting for project {project_id}"
                )
            if self._admission_is_full():
                raise AgentQueueFullError(
                    "Agent admission queue is full; retry after active work completes"
                )
            if self._owner_admission_is_full(owner_id):
                raise AgentQueueFullError(
                    "Agent admission quota for this user is full; retry after active work completes"
                )
            self._starting_projects.add(project_id)
            self._project_owners[project_id] = owner_id

        execution_id: str | None = None
        scheduled = False
        unscheduled_interrupted = False
        try:
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

            if execution_id is None:
                raise RuntimeError("Agent execution identifier was not assigned")

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
            async with self._lock:
                runtime_stopped = (
                    not self._accepting or project_id in self._deleting_projects
                )
            if runtime_stopped:
                await self._persist_unscheduled_interruption(
                    db=db,
                    project_id=project_id,
                    execution_id=execution_id,
                    reason="Agent runtime stopped before scheduling",
                )
                unscheduled_interrupted = True
                raise AgentRuntimeUnavailableError(
                    "Agent runtime stopped before execution could be scheduled"
                )

            execution = _ScheduledExecution(
                project_id=project_id,
                execution_id=execution_id,
                db=db,
            )
            background = asyncio.create_task(
                self._run_scheduled(
                    scheduled=execution,
                    project=project,
                    topic=topic,
                    target_papers=target_papers,
                    target_words=target_words,
                    quality_threshold=quality_threshold,
                    sse_manager=sse_manager,
                    resume=resume_from_checkpoint,
                ),
                name=f"agent:{project_id}:{execution_id}",
            )
            stopped_before_registration = False
            async with self._lock:
                # Project deletion/shutdown can begin between the preceding
                # check and task creation. Do not leak a pending execution.
                if not self._accepting or project_id in self._deleting_projects:
                    background.cancel()
                    stopped_before_registration = True
                else:
                    self._tasks[project_id] = background
                    self._scheduled[project_id] = execution
                    scheduled = True
            if stopped_before_registration:
                await self._persist_unscheduled_interruption(
                    db=db,
                    project_id=project_id,
                    execution_id=execution_id,
                    reason="Agent runtime stopped before scheduling",
                )
                unscheduled_interrupted = True
                raise AgentRuntimeUnavailableError(
                    "Agent runtime stopped before execution could be scheduled"
                )
            return execution_id
        except BaseException:
            if (
                execution_id is not None
                and not scheduled
                and not unscheduled_interrupted
            ):
                with contextlib.suppress(Exception):
                    await self._persist_unscheduled_interruption(
                        db=db,
                        project_id=project_id,
                        execution_id=execution_id,
                        reason="Agent execution was not scheduled",
                    )
            raise
        finally:
            async with self._lock:
                self._starting_projects.discard(project_id)
                if not scheduled:
                    self._project_owners.pop(project_id, None)

    async def _persist_unscheduled_interruption(
        self,
        *,
        db: Any,
        project_id: str,
        execution_id: str,
        reason: str,
    ) -> None:
        """Close a persisted pending row when no task can own its cleanup."""

        await db.update_agent_execution(
            execution_id,
            "interrupted",
            error_message=reason,
        )
        await db.update_project_status(project_id, "interrupted")

    async def _persist_queued_interruption(
        self,
        scheduled: _ScheduledExecution,
        *,
        reason: str,
    ) -> None:
        """Persist queued cancellation exactly once, including pre-start races."""

        async with scheduled.persistence_lock:
            if scheduled.interruption_persisted:
                return
            await self._persist_unscheduled_interruption(
                db=scheduled.db,
                project_id=scheduled.project_id,
                execution_id=scheduled.execution_id,
                reason=reason,
            )
            scheduled.interruption_persisted = True

    async def _run_scheduled(
        self,
        *,
        scheduled: _ScheduledExecution,
        project: dict[str, Any],
        topic: str,
        target_papers: int,
        target_words: int,
        quality_threshold: float,
        sse_manager: Any,
        resume: bool,
    ) -> None:
        """Run one persisted execution after FIFO admission to the active pool."""

        project_id = scheduled.project_id
        try:
            async with self._run_gate.slot(timeout=self._queue_wait_timeout_seconds):
                scheduled.started = True
                await self._run(
                    project=project,
                    topic=topic,
                    execution_id=scheduled.execution_id,
                    target_papers=target_papers,
                    target_words=target_words,
                    quality_threshold=quality_threshold,
                    sse_manager=sse_manager,
                    resume=resume,
                    db=scheduled.db,
                )
        except ConcurrencyQueueFullError as error:
            await self._persist_unscheduled_interruption(
                db=scheduled.db,
                project_id=project_id,
                execution_id=scheduled.execution_id,
                reason=f"Agent scheduling queue overflow: {error}",
            )
            logger.error(
                "Agent scheduling queue overflow",
                project_id=project_id,
                execution_id=scheduled.execution_id,
            )
        except ConcurrencyQueueTimeoutError as error:
            await self._persist_unscheduled_interruption(
                db=scheduled.db,
                project_id=project_id,
                execution_id=scheduled.execution_id,
                reason=f"Agent scheduling deadline exceeded: {error}",
            )
            logger.warning(
                "Agent execution expired in scheduling queue",
                project_id=project_id,
                execution_id=scheduled.execution_id,
            )
        except asyncio.CancelledError:
            if not scheduled.started:
                with contextlib.suppress(Exception):
                    await self._persist_queued_interruption(
                        scheduled,
                        reason="Execution cancelled before the Agent run started",
                    )
            raise
        finally:
            async with self._lock:
                current = self._tasks.get(project_id)
                if current is asyncio.current_task():
                    self._tasks.pop(project_id, None)
                    self._scheduled.pop(project_id, None)
                    self._project_owners.pop(project_id, None)

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

    async def cancel(self, project_id: str) -> str:
        """Cancel queued or active work without indefinitely blocking the API."""

        async with self._lock:
            task = self._tasks.get(project_id)
            scheduled = self._scheduled.get(project_id)
            if task is None or task.done():
                raise AgentNotRunningError(
                    f"Agent is not running for project {project_id}"
                )
            task.cancel()
        await self._await_cancelled_task(task, scheduled)
        return scheduled.execution_id if scheduled is not None else ""

    async def _await_cancelled_task(
        self,
        task: asyncio.Task[None],
        scheduled: _ScheduledExecution | None,
    ) -> None:
        """Bound cancellation waits and close a task cancelled before first step."""

        try:
            await asyncio.wait_for(
                asyncio.shield(task), timeout=self._cancel_timeout_seconds
            )
        except asyncio.CancelledError:
            pass
        except TimeoutError as error:
            if scheduled is not None:
                with contextlib.suppress(Exception):
                    await self._persist_queued_interruption(
                        scheduled,
                        reason="Execution cancellation deadline exceeded",
                    )
            raise AgentCancellationTimeoutError(
                "Agent cancellation is still draining provider work"
            ) from error
        finally:
            if scheduled is not None and not scheduled.started:
                with contextlib.suppress(Exception):
                    await self._persist_queued_interruption(
                        scheduled,
                        reason="Execution cancelled before the Agent run started",
                    )
            if scheduled is not None and task.done():
                # A task cancelled before its first event-loop step never
                # enters _run_scheduled's finally block. Release its local
                # admission record here so it cannot consume queue capacity.
                async with self._lock:
                    if self._tasks.get(scheduled.project_id) is task:
                        self._tasks.pop(scheduled.project_id, None)
                        self._scheduled.pop(scheduled.project_id, None)
                        self._project_owners.pop(scheduled.project_id, None)

    async def begin_project_deletion(self, project_id: str) -> None:
        """Block new starts, cancel an active task, and await its full tree."""

        async with self._lock:
            self._deleting_projects.add(project_id)
            task = self._tasks.get(project_id)
            scheduled = self._scheduled.get(project_id)
            if task is not None and not task.done():
                task.cancel()
        if task is not None:
            try:
                await self._await_cancelled_task(task, scheduled)
            except AgentCancellationTimeoutError:
                logger.warning(
                    "Agent cancellation timed out during project deletion",
                    project_id=project_id,
                )

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
        """Stop accepting work and bound shutdown waits for provider cleanup."""

        self._accepting = False
        async with self._lock:
            tasks = [
                (task, self._scheduled.get(project_id))
                for project_id, task in self._tasks.items()
            ]
            for task in tasks:
                task[0].cancel()
        if tasks:
            results = await asyncio.gather(
                *(
                    self._await_cancelled_task(task, scheduled)
                    for task, scheduled in tasks
                ),
                return_exceptions=True,
            )
            for result in results:
                if isinstance(result, AgentCancellationTimeoutError):
                    logger.warning("Agent task exceeded shutdown cancellation deadline")
        async with self._lock:
            self._tasks.clear()
            self._scheduled.clear()
            self._starting_projects.clear()
            self._project_owners.clear()
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
