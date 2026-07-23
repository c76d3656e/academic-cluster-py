"""Task-local observability context for the production Agent workflow."""

from __future__ import annotations

from contextvars import ContextVar, Token

import structlog

_current_project_id: ContextVar[str | None] = ContextVar(
    "current_project_id", default=None
)
_current_execution_id: ContextVar[str | None] = ContextVar(
    "current_execution_id", default=None
)
_current_agent_phase: ContextVar[str | None] = ContextVar(
    "current_agent_phase", default=None
)


def setup_structlog(log_level: str = "INFO") -> None:
    """Configure the process-wide structured logging pipeline."""

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(structlog, log_level.upper(), 20)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_current_project() -> str | None:
    """Return the project associated with the current async task."""

    return _current_project_id.get()


def get_current_execution() -> str | None:
    """Return the Agent execution associated with the current async task."""

    return _current_execution_id.get()


def get_current_agent_phase() -> str | None:
    """Return the Agent phase associated with the current async task."""

    return _current_agent_phase.get()


def push_current_project(project_id: str | None) -> Token[str | None]:
    """Set project context and return a token that restores the prior value."""

    return _current_project_id.set(project_id)


def pop_current_project(token: Token[str | None]) -> None:
    """Restore project context captured by :func:`push_current_project`."""

    _current_project_id.reset(token)


def push_current_execution(execution_id: str | None) -> Token[str | None]:
    """Set execution context and return a token that restores the prior value."""

    return _current_execution_id.set(execution_id)


def pop_current_execution(token: Token[str | None]) -> None:
    """Restore execution context captured by :func:`push_current_execution`."""

    _current_execution_id.reset(token)


def push_current_agent_phase(phase: str | None) -> Token[str | None]:
    """Set phase context and return a token that restores the prior value."""

    return _current_agent_phase.set(phase)


def pop_current_agent_phase(token: Token[str | None]) -> None:
    """Restore phase context captured by :func:`push_current_agent_phase`."""

    _current_agent_phase.reset(token)
