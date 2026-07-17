"""Optional, fail-open Langfuse tracing for Agent executions and graph nodes.

The adapter targets the Langfuse Python SDK v4 API while keeping Langfuse an
optional dependency.  It never initializes the SDK without both credentials,
does not capture node inputs or outputs by default, and must never change Agent
control flow when tracing is unavailable or broken.
"""

from __future__ import annotations

import asyncio
import functools
import importlib
import inspect
import math
import re
import threading
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from hashlib import sha256
from itertools import islice
from typing import Any, ParamSpec, TypeVar, cast

import structlog

logger = structlog.get_logger()

_P = ParamSpec("_P")
_R = TypeVar("_R")

_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_RE = re.compile(
    r"(?:^|[_\-.])(?:api[_-]?key|authorization|cookie|credential|jwt|pass(?:word|wd)?|"
    r"private[_-]?key|refresh[_-]?token|secret|session[_-]?token|token)(?:$|[_\-.])",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|password|passwd|secret|token)\s*[:=]\s*"
    r"([^\s,;]+)"
)
_KNOWN_KEY_RE = re.compile(r"\b(?:sk|pk|sk-lf|pk-lf)-[A-Za-z0-9_-]{8,}\b")


@dataclass(frozen=True, slots=True)
class LangfuseConfig:
    """Security-conscious configuration for the optional tracing adapter."""

    enabled: bool = False
    public_key: str | None = None
    secret_key: str | None = field(default=None, repr=False)
    base_url: str | None = None
    tracing_environment: str | None = None
    release: str | None = None
    sample_rate: float = 1.0
    capture_inputs: bool = False
    capture_outputs: bool = False
    max_value_chars: int = 2000

    @classmethod
    def from_settings(cls, settings: Any = None) -> LangfuseConfig:
        """Load the application's validated Langfuse settings."""

        if settings is None:
            try:
                from ..config import get_settings

                settings = get_settings()
            except Exception:
                return cls()
        public_key = str(getattr(settings, "langfuse_public_key", "") or "").strip()
        secret_key = str(getattr(settings, "langfuse_secret_key", "") or "").strip()
        capture_node_io = bool(getattr(settings, "langfuse_capture_node_io", False))
        try:
            sample_rate = float(getattr(settings, "langfuse_sample_rate", 1.0))
        except (TypeError, ValueError, OverflowError):
            sample_rate = 1.0
        if not math.isfinite(sample_rate):
            sample_rate = 1.0
        return cls(
            enabled=bool(getattr(settings, "langfuse_enabled", False)),
            public_key=public_key or None,
            secret_key=secret_key or None,
            base_url=str(getattr(settings, "langfuse_base_url", "") or "").strip()
            or None,
            tracing_environment=str(
                getattr(settings, "langfuse_tracing_environment", "") or ""
            ).strip()
            or None,
            release=str(getattr(settings, "langfuse_release", "") or "").strip()
            or None,
            sample_rate=max(0.0, min(sample_rate, 1.0)),
            capture_inputs=capture_node_io,
            capture_outputs=capture_node_io,
        )


def _redact_text(value: str, *, max_chars: int) -> str:
    redacted = _BEARER_RE.sub("Bearer " + _REDACTED, value)
    redacted = _KNOWN_KEY_RE.sub(_REDACTED, redacted)
    redacted = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}={_REDACTED}", redacted
    )
    if len(redacted) > max_chars:
        return redacted[:max_chars] + "...[truncated]"
    return redacted


def sanitize_langfuse_payload(
    value: Any,
    *,
    max_value_chars: int = 2000,
    max_depth: int = 4,
    max_items: int = 25,
) -> Any:
    """Return a bounded, JSON-friendly value with common secrets removed."""

    bounded_chars = max(128, min(max_value_chars, 20000))
    bounded_depth = max(1, min(max_depth, 8))
    bounded_items = max(1, min(max_items, 100))
    seen: set[int] = set()

    def clean(item: Any, depth: int) -> Any:
        if item is None or isinstance(item, (bool, int)):
            return item
        if isinstance(item, float):
            return item if math.isfinite(item) else str(item)
        if isinstance(item, str):
            return _redact_text(item, max_chars=bounded_chars)
        if isinstance(item, (bytes, bytearray, memoryview)):
            return f"<{type(item).__name__}:{len(item)} bytes>"
        if depth >= bounded_depth:
            return f"<{type(item).__name__}:max-depth>"

        identity = id(item)
        if identity in seen:
            return f"<{type(item).__name__}:recursive>"
        seen.add(identity)
        try:
            if isinstance(item, Mapping):
                output: dict[str, Any] = {}
                for raw_key, raw_value in islice(item.items(), bounded_items):
                    key = _redact_text(str(raw_key), max_chars=200)
                    output[key] = (
                        _REDACTED
                        if _SENSITIVE_KEY_RE.search(key)
                        else clean(raw_value, depth + 1)
                    )
                remaining = max(0, len(item) - bounded_items)
                if remaining:
                    output["__truncated_items__"] = remaining
                return output
            if isinstance(item, Sequence) and not isinstance(item, str):
                output_items = [
                    clean(item[index], depth + 1)
                    for index in range(min(len(item), bounded_items))
                ]
                if len(item) > bounded_items:
                    output_items.append(
                        {"__truncated_items__": len(item) - bounded_items}
                    )
                return output_items
            if isinstance(item, (set, frozenset)):
                return [
                    clean(child, depth + 1) for child in islice(item, bounded_items)
                ]
            model_dump = getattr(item, "model_dump", None)
            if callable(model_dump):
                for dump_kwargs in ({"mode": "json"}, {"mode": "python"}, {}):
                    try:
                        dumped = model_dump(**dump_kwargs)
                    except (TypeError, ValueError):
                        continue
                    except Exception as error:
                        return f"<unavailable:{type(error).__name__}>"
                    return clean(dumped, depth + 1)
                return f"<{type(item).__name__}>"
            if is_dataclass(item) and not isinstance(item, type):
                try:
                    dumped_dataclass = {
                        item_field.name: getattr(item, item_field.name)
                        for item_field in fields(item)
                    }
                except Exception as error:
                    return f"<unavailable:{type(error).__name__}>"
                return clean(dumped_dataclass, depth + 1)
            return f"<{type(item).__name__}>"
        finally:
            seen.discard(identity)

    try:
        return clean(value, 0)
    except Exception as error:
        return f"<unavailable:{type(error).__name__}>"


@dataclass(slots=True)
class _ActiveObservation:
    manager: Any
    observation: Any
    propagation_manager: Any = None


class LangfuseObservability:
    """Fail-open execution and node tracing backed by the Langfuse v4 SDK."""

    def __init__(
        self,
        *,
        config: LangfuseConfig | None = None,
        client: Any = None,
        propagate_attributes: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config or LangfuseConfig.from_settings()
        self._client: Any = None
        self._propagate_attributes = propagate_attributes
        self._enabled = False
        self._state_lock = threading.RLock()

        if not self.config.enabled:
            return
        if client is not None:
            self._client = client
            self._enabled = True
            return
        if not self.config.public_key or not self.config.secret_key:
            return

        try:
            module = importlib.import_module("langfuse")
            client_type = module.Langfuse
            kwargs: dict[str, Any] = {
                "public_key": self.config.public_key,
                "secret_key": self.config.secret_key,
                "tracing_enabled": True,
                "mask": lambda payload: sanitize_langfuse_payload(
                    payload,
                    max_value_chars=self.config.max_value_chars,
                ),
            }
            if self.config.base_url:
                kwargs["base_url"] = self.config.base_url
            if self.config.tracing_environment:
                kwargs["environment"] = self.config.tracing_environment
            if self.config.release:
                kwargs["release"] = self.config.release
            kwargs["sample_rate"] = self.config.sample_rate
            candidate = client_type(**kwargs)
            if not callable(getattr(candidate, "start_as_current_observation", None)):
                return
            self._client = candidate
            self._propagate_attributes = getattr(module, "propagate_attributes", None)
            self._enabled = True
        except Exception as error:
            logger.warning(
                "Langfuse observability initialization failed open",
                error_type=type(error).__name__,
            )

    @property
    def enabled(self) -> bool:
        return self._enabled and self._client is not None

    def wrap_execution(
        self,
        function: Callable[_P, _R],
        *,
        contract_version: str | None = None,
        artifact_version: str | None = None,
        context_version: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        capture_input: bool | None = None,
        capture_output: bool | None = None,
    ) -> Callable[_P, _R]:
        """Wrap a sync or async execution entrypoint as one Agent observation."""

        return self._wrap(
            function,
            scope="execution",
            observation_name="agent.execution",
            observation_type="agent",
            contract_version=contract_version,
            artifact_version=artifact_version,
            context_version=context_version,
            metadata=metadata,
            capture_input=capture_input,
            capture_output=capture_output,
        )

    def wrap_node(
        self,
        function: Callable[_P, _R],
        *,
        node_name: str | None = None,
        contract_version: str | None = None,
        artifact_version: str | None = None,
        context_version: str | None = None,
        metadata: Mapping[str, Any] | None = None,
        capture_input: bool | None = None,
        capture_output: bool | None = None,
    ) -> Callable[_P, _R]:
        """Wrap a sync or async graph node as a child/span observation."""

        resolved_name = (node_name or function.__name__).strip() or "unknown"
        return self._wrap(
            function,
            scope="node",
            observation_name=f"agent.node.{resolved_name}",
            observation_type="span",
            contract_version=contract_version,
            artifact_version=artifact_version,
            context_version=context_version,
            metadata=metadata,
            capture_input=capture_input,
            capture_output=capture_output,
        )

    def _wrap(
        self,
        function: Callable[_P, _R],
        *,
        scope: str,
        observation_name: str,
        observation_type: str,
        contract_version: str | None,
        artifact_version: str | None,
        context_version: str | None,
        metadata: Mapping[str, Any] | None,
        capture_input: bool | None,
        capture_output: bool | None,
    ) -> Callable[_P, _R]:
        capture_inputs = (
            self.config.capture_inputs if capture_input is None else capture_input
        )
        capture_outputs = (
            self.config.capture_outputs if capture_output is None else capture_output
        )
        try:
            call_signature: inspect.Signature | None = inspect.signature(function)
        except (TypeError, ValueError):
            call_signature = None

        if inspect.iscoroutinefunction(function):
            async_function = cast(Callable[_P, Awaitable[Any]], function)

            @functools.wraps(function)
            async def async_wrapped(*args: _P.args, **kwargs: _P.kwargs) -> Any:
                active = self._start(
                    scope=scope,
                    observation_name=observation_name,
                    observation_type=observation_type,
                    args=args,
                    kwargs=kwargs,
                    runtime_values=_bound_arguments(call_signature, args, kwargs),
                    contract_version=contract_version,
                    artifact_version=artifact_version,
                    context_version=context_version,
                    metadata=metadata,
                    capture_inputs=capture_inputs,
                )
                try:
                    result = await async_function(*args, **kwargs)
                except BaseException as error:
                    self._finish(
                        active,
                        error=error,
                        output=None,
                        capture_output=False,
                    )
                    raise
                self._finish(
                    active,
                    error=None,
                    output=result,
                    capture_output=capture_outputs,
                )
                return result

            return cast(Callable[_P, _R], async_wrapped)

        @functools.wraps(function)
        def sync_wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            active = self._start(
                scope=scope,
                observation_name=observation_name,
                observation_type=observation_type,
                args=args,
                kwargs=kwargs,
                runtime_values=_bound_arguments(call_signature, args, kwargs),
                contract_version=contract_version,
                artifact_version=artifact_version,
                context_version=context_version,
                metadata=metadata,
                capture_inputs=capture_inputs,
            )
            try:
                result = function(*args, **kwargs)
            except BaseException as error:
                self._finish(
                    active,
                    error=error,
                    output=None,
                    capture_output=False,
                )
                raise
            self._finish(
                active,
                error=None,
                output=result,
                capture_output=capture_outputs,
            )
            return result

        return sync_wrapped

    def _start(
        self,
        *,
        scope: str,
        observation_name: str,
        observation_type: str,
        args: tuple[Any, ...],
        kwargs: Mapping[str, Any],
        runtime_values: Mapping[str, Any],
        contract_version: str | None,
        artifact_version: str | None,
        context_version: str | None,
        metadata: Mapping[str, Any] | None,
        capture_inputs: bool,
    ) -> _ActiveObservation | None:
        client = self._client if self.enabled else None
        if client is None:
            return None

        project_id, execution_id = _resolve_runtime_ids(args, runtime_values)
        trace_id = _create_execution_trace_id(client, execution_id)
        trace_context: dict[str, str] | None = {"trace_id": trace_id}
        if scope == "node":
            try:
                current_trace_id = client.get_current_trace_id()
            except Exception:
                current_trace_id = None
            if current_trace_id == trace_id:
                trace_context = None

        observation_metadata = _observation_metadata(
            scope=scope,
            observation_name=observation_name,
            project_id=project_id,
            execution_id=execution_id,
            contract_version=contract_version,
            artifact_version=artifact_version,
            context_version=context_version,
            metadata=metadata,
            max_value_chars=self.config.max_value_chars,
        )
        captured_input = (
            sanitize_langfuse_payload(
                {"args": args, "kwargs": kwargs},
                max_value_chars=self.config.max_value_chars,
            )
            if capture_inputs
            else None
        )
        start_kwargs: dict[str, Any] = {
            "name": observation_name,
            "as_type": observation_type,
            "input": captured_input,
            "metadata": observation_metadata,
            "version": contract_version,
        }
        if trace_context is not None:
            start_kwargs["trace_context"] = trace_context

        try:
            manager = client.start_as_current_observation(**start_kwargs)
            observation = manager.__enter__()
        except Exception as error:
            logger.debug(
                "Langfuse observation start failed open",
                operation=observation_name,
                error_type=type(error).__name__,
            )
            return None

        active = _ActiveObservation(manager=manager, observation=observation)
        propagation = self._propagate_attributes
        if callable(propagation):
            try:
                propagation_metadata = {
                    key: str(value)[:200]
                    for key, value in observation_metadata.items()
                    if key
                    in {
                        "project_id",
                        "execution_id",
                        "contract_version",
                        "artifact_version",
                        "context_version",
                    }
                }
                propagation_manager = propagation(
                    session_id=_ascii_identifier(execution_id),
                    metadata=propagation_metadata,
                    version=contract_version,
                    trace_name="agent.execution",
                )
                propagation_manager.__enter__()
                active.propagation_manager = propagation_manager
            except Exception as error:
                logger.debug(
                    "Langfuse trace attribute propagation failed open",
                    operation=observation_name,
                    error_type=type(error).__name__,
                )
        return active

    def _finish(
        self,
        active: _ActiveObservation | None,
        *,
        error: BaseException | None,
        output: Any,
        capture_output: bool,
    ) -> None:
        if active is None:
            return

        if error is None:
            update_kwargs: dict[str, Any] = {"metadata": {"status": "succeeded"}}
            if capture_output:
                update_kwargs["output"] = sanitize_langfuse_payload(
                    output,
                    max_value_chars=self.config.max_value_chars,
                )
        elif isinstance(error, asyncio.CancelledError):
            status_message = _redact_text(
                str(error) or type(error).__name__,
                max_chars=min(self.config.max_value_chars, 500),
            )
            update_kwargs = {
                "metadata": {
                    "status": "cancelled",
                    "error_type": type(error).__name__,
                },
                "level": "WARNING",
                "status_message": status_message,
            }
        else:
            status_message = _redact_text(
                str(error) or type(error).__name__,
                max_chars=min(self.config.max_value_chars, 500),
            )
            update_kwargs = {
                "metadata": {
                    "status": "failed",
                    "error_type": type(error).__name__,
                },
                "level": "ERROR",
                "status_message": status_message,
            }

        try:
            active.observation.update(**update_kwargs)
        except Exception as sdk_error:
            logger.debug(
                "Langfuse observation update failed open",
                error_type=type(sdk_error).__name__,
            )

        exit_error = None if isinstance(error, asyncio.CancelledError) else error
        exc_type = type(exit_error) if exit_error is not None else None
        traceback = exit_error.__traceback__ if exit_error is not None else None
        if active.propagation_manager is not None:
            try:
                active.propagation_manager.__exit__(exc_type, exit_error, traceback)
            except Exception as sdk_error:
                logger.debug(
                    "Langfuse propagation cleanup failed open",
                    error_type=type(sdk_error).__name__,
                )
        try:
            active.manager.__exit__(exc_type, exit_error, traceback)
        except Exception as sdk_error:
            logger.debug(
                "Langfuse observation cleanup failed open",
                error_type=type(sdk_error).__name__,
            )

    def flush(self) -> None:
        """Synchronously flush pending telemetry without surfacing SDK errors."""

        client = self._client if self.enabled else None
        if client is None:
            return
        try:
            client.flush()
        except Exception as error:
            logger.warning(
                "Langfuse flush failed open", error_type=type(error).__name__
            )

    async def aflush(self) -> None:
        """Flush pending telemetry without blocking the current event loop."""

        await asyncio.to_thread(self.flush)

    def shutdown(self) -> None:
        """Synchronously stop the SDK; repeated calls are safe no-ops."""

        with self._state_lock:
            client = self._client
            self._client = None
            self._enabled = False
        if client is None:
            return
        try:
            client.shutdown()
        except Exception as error:
            logger.warning(
                "Langfuse shutdown failed open", error_type=type(error).__name__
            )

    async def ashutdown(self) -> None:
        """Stop the SDK without blocking the current event loop."""

        await asyncio.to_thread(self.shutdown)


def _resolve_runtime_ids(
    args: tuple[Any, ...], kwargs: Mapping[str, Any]
) -> tuple[str | None, str | None]:
    project_id = _identifier_from(kwargs, "project_id")
    execution_id = _identifier_from(kwargs, "execution_id")
    if project_id is None or execution_id is None:
        for candidate in args[:3]:
            project_id = project_id or _identifier_from(candidate, "project_id")
            execution_id = execution_id or _identifier_from(candidate, "execution_id")
            if project_id and execution_id:
                break
    try:
        from .observability import get_current_execution, get_current_project

        project_id = project_id or get_current_project()
        execution_id = execution_id or get_current_execution()
    except Exception:
        pass
    return project_id, execution_id


def _bound_arguments(
    signature: inspect.Signature | None,
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> Mapping[str, Any]:
    if signature is None:
        return kwargs
    try:
        return signature.bind_partial(*args, **kwargs).arguments
    except (TypeError, ValueError):
        return kwargs


def _identifier_from(container: Any, name: str) -> str | None:
    try:
        value = (
            container.get(name)
            if isinstance(container, Mapping)
            else getattr(container, name, None)
        )
    except Exception:
        return None
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _create_execution_trace_id(client: Any, execution_id: str | None) -> str:
    seed = f"academic-cluster:execution:{execution_id or uuid.uuid4().hex}"
    try:
        trace_id = client.create_trace_id(seed=seed)
        if isinstance(trace_id, str) and re.fullmatch(r"[0-9a-f]{32}", trace_id):
            return trace_id
    except Exception:
        pass
    return sha256(seed.encode("utf-8")).hexdigest()[:32]


def _ascii_identifier(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.encode("ascii", errors="ignore").decode("ascii").strip()
    return normalized[:200] or None


def _version_value(value: str | None) -> str:
    if not value:
        return "unspecified"
    return _redact_text(str(value), max_chars=200)


def _observation_metadata(
    *,
    scope: str,
    observation_name: str,
    project_id: str | None,
    execution_id: str | None,
    contract_version: str | None,
    artifact_version: str | None,
    context_version: str | None,
    metadata: Mapping[str, Any] | None,
    max_value_chars: int,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "component": "academic-cluster",
        "scope": scope,
        "observation_name": observation_name,
        "node_name": (
            observation_name.removeprefix("agent.node.")
            if scope == "node"
            else "execution"
        ),
        "project_id": project_id or "unknown",
        "execution_id": execution_id or "unknown",
        "contract_version": _version_value(contract_version),
        "artifact_version": _version_value(artifact_version),
        "context_version": _version_value(context_version),
    }
    if metadata:
        result["attributes"] = sanitize_langfuse_payload(
            metadata,
            max_value_chars=max_value_chars,
        )
    return result


_global_lock = threading.Lock()
_global_observability: LangfuseObservability | None = None


def get_langfuse_observability() -> LangfuseObservability:
    """Return the process-wide optional Langfuse adapter."""

    global _global_observability
    with _global_lock:
        if _global_observability is None:
            _global_observability = LangfuseObservability()
        return _global_observability


def flush_langfuse_observability() -> None:
    get_langfuse_observability().flush()


async def aflush_langfuse_observability() -> None:
    await get_langfuse_observability().aflush()


def shutdown_langfuse_observability() -> None:
    global _global_observability
    with _global_lock:
        observability = _global_observability
        _global_observability = None
    if observability is not None:
        observability.shutdown()


async def ashutdown_langfuse_observability() -> None:
    global _global_observability
    with _global_lock:
        observability = _global_observability
        _global_observability = None
    if observability is not None:
        await observability.ashutdown()
