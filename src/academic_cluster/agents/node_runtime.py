"""Runtime enforcement and tracing for production Agent node contracts."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import time
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any, TypeVar

import structlog
from pydantic import BaseModel

from ..services.langfuse_observability import get_langfuse_observability
from .node_contracts import (
    CONTRACT_VERSION,
    MANIFEST_VERSION,
    NODE_NAMES,
    NodeContractValidationError,
    NodeName,
    VersionedArtifact,
    build_invocation_manifest,
    get_node_contract,
    validate_node_output,
)

logger = structlog.get_logger()

_StateT = TypeVar("_StateT", bound=BaseModel)
_NodeHandler = Callable[[_StateT], Coroutine[Any, Any, dict[str, Any]]]


def _artifact_digest(artifact: VersionedArtifact) -> str:
    canonical = json.dumps(
        artifact.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def enforce_node_contract(
    node_name: NodeName,
) -> Callable[[_NodeHandler[_StateT]], _NodeHandler[_StateT]]:
    """Validate, describe, and trace one node without changing its state update."""

    contract = get_node_contract(node_name)
    input_ref = (
        f"{contract.input_artifact.artifact_id}@"
        f"{contract.input_artifact.version}"
    )
    output_ref = (
        f"{contract.output_artifact.artifact_id}@"
        f"{contract.output_artifact.version}"
    )

    def decorate(function: _NodeHandler[_StateT]) -> _NodeHandler[_StateT]:
        @functools.wraps(function)
        async def wrapped(state: _StateT) -> dict[str, Any]:
            try:
                invocation = build_invocation_manifest(node_name, state)
            except NodeContractValidationError:
                logger.exception(
                    "Agent node input contract rejected",
                    node=node_name,
                    contract_version=contract.version,
                    input_artifact=input_ref,
                )
                raise

            started = time.monotonic()
            result_holder: list[dict[str, Any]] = []
            observability = get_langfuse_observability()
            capture_node_io = bool(observability.config.capture_outputs)

            async def execute(current: _StateT) -> dict[str, Any]:
                logger.info(
                    "Agent node contract started",
                    node=node_name,
                    contract_version=contract.version,
                    invocation_id=invocation.invocation_id,
                    input_artifact=input_ref,
                    input_schema_digest=invocation.input_schema_digest,
                )
                try:
                    result = await function(current)
                except asyncio.CancelledError:
                    logger.info(
                        "Agent node contract cancelled",
                        node=node_name,
                        invocation_id=invocation.invocation_id,
                    )
                    raise
                except Exception as error:
                    logger.exception(
                        "Agent node escaped its declared update semantics",
                        node=node_name,
                        invocation_id=invocation.invocation_id,
                        error_type=type(error).__name__,
                    )
                    raise

                try:
                    output_artifact = validate_node_output(node_name, result)
                except NodeContractValidationError:
                    logger.exception(
                        "Agent node output contract rejected",
                        node=node_name,
                        invocation_id=invocation.invocation_id,
                        output_artifact=output_ref,
                    )
                    raise

                result_holder.append(result)
                elapsed_ms = int((time.monotonic() - started) * 1000)
                logger.info(
                    "Agent node contract completed",
                    node=node_name,
                    invocation_id=invocation.invocation_id,
                    output_artifact=output_ref,
                    output_variant=output_artifact.variant,
                    elapsed_ms=elapsed_ms,
                )
                # Langfuse receives only this schema-level summary. The actual node
                # payload is returned from ``result_holder`` below and remains local
                # unless operators explicitly enable node I/O capture.
                trace_summary = {
                    "artifact_ref": output_ref,
                    "artifact_digest": _artifact_digest(output_artifact),
                    "variant": output_artifact.variant,
                    "status": result.get("status"),
                    "fields": sorted(result),
                    "elapsed_ms": elapsed_ms,
                }
                return result if capture_node_io else trace_summary

            traced = observability.wrap_node(
                execute,
                node_name=node_name,
                contract_version=contract.version,
                artifact_version=contract.output_artifact.version,
                context_version=MANIFEST_VERSION,
                metadata={
                    "invocation_id": invocation.invocation_id,
                    "input_artifact_ref": input_ref,
                    "input_schema_digest": invocation.input_schema_digest,
                    "output_artifact_ref": output_ref,
                    "declared_error_codes": [
                        error.code for error in contract.errors.declared_errors
                    ],
                    "dependency_operations": [
                        item.operation for item in contract.context.invocations
                    ],
                },
                capture_input=bool(observability.config.capture_inputs),
                capture_output=True,
            )
            await traced(state)
            if len(result_holder) != 1:
                raise RuntimeError(
                    f"contracted node {node_name} did not produce exactly one update"
                )
            return result_holder[0]

        return wrapped

    return decorate


def trace_agent_execution[**P, R](
    function: Callable[P, Awaitable[R]],
) -> Callable[P, Awaitable[R]]:
    """Create one lazy Langfuse root observation around a graph execution."""

    @functools.wraps(function)
    async def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
        traced = get_langfuse_observability().wrap_execution(
            function,
            contract_version=CONTRACT_VERSION,
            artifact_version=CONTRACT_VERSION,
            context_version=MANIFEST_VERSION,
            metadata={
                "graph": "academic-cluster.agent.v1",
                "nodes": list(NODE_NAMES),
            },
            capture_input=False,
            capture_output=False,
        )
        return await traced(*args, **kwargs)

    return wrapped
