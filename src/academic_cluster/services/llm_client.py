"""
统一 LLM 客户端工厂

通过 LiteLLM Router 发出所有 LLM 请求，由 Router 处理路由、重试、
故障转移、RPM 限速和 cooldown。

所有 agent 和 node 应通过此模块获取 LLM 客户端。
"""

import asyncio
import contextlib
import json
import re
import secrets
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from types import SimpleNamespace
from typing import Any

import structlog
from langchain_core.language_models.base import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableBinding
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from pydantic import ConfigDict

from .concurrency import BoundedFifoGate

logger = structlog.get_logger()

def _default_routing_policy() -> SimpleNamespace:
    """Return TOML defaults for compatibility clients outside the provider pool."""

    from .runtime_policy import config_definitions

    definitions = config_definitions()
    return SimpleNamespace(
        provider_request_timeout_seconds=float(
            definitions["provider.request_timeout_seconds"]["value"]
        ),
        provider_timeout_retries=int(definitions["provider.timeout_retries"]["value"]),
        provider_timeout_grace_seconds=float(
            definitions["provider.timeout_grace_seconds"]["value"]
        ),
        provider_retry_delay_seconds=float(
            definitions["provider.retry_delay_seconds"]["value"]
        ),
    )


_TASK_TAGS: dict[str, set[str]] = {
    "kg":       {"kg", "public"},
    "evidence": {"ec", "public"},
    "outline":  {"ol", "public"},
    "writing":  {"wr", "public"},
    "search":   {"se", "public"},
    "default":  {"public"},
}

_rr_counter = 0
_llm_request_gate: BoundedFifoGate | None = None
_llm_request_gate_config: tuple[int, int, float] | None = None

_THINK_BLOCK_RE = re.compile(
    r"<think\b[^>]*>.*?(?:</think>|$)", re.IGNORECASE | re.DOTALL
)


async def _cancel_and_wait(task: asyncio.Task[Any] | None) -> None:
    """Cancel an in-flight provider task and always consume its terminal state."""

    if task is None:
        return
    if not task.done():
        task.cancel()
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task


def _messages_to_openai(input: Any) -> list[dict[str, Any]]:
    """将 LangChain 消息或字符串转为 OpenAI 消息 dict 列表（供 Router 使用）。"""
    from langchain_core.messages.utils import convert_to_openai_messages

    if isinstance(input, str):
        return [{"role": "user", "content": input}]
    if isinstance(input, list):
        return convert_to_openai_messages(input)
    return [{"role": "user", "content": str(input)}]


def _router_response_to_aimessage(response: Any, provider_alias: str = "") -> AIMessage:
    """将 LiteLLM Router 的响应 dict 转为 LangChain AIMessage。"""
    choices = getattr(response, "choices", None) or response.get("choices", [])
    choice = choices[0] if choices else {}
    msg_dict = (
        choice.get("message", {})
        if isinstance(choice, dict)
        else getattr(choice, "message", {})
    )
    content = (
        msg_dict.get("content", "")
        if isinstance(msg_dict, dict)
        else getattr(msg_dict, "content", "")
    )
    finish_reason = (
        choice.get("finish_reason", "")
        if isinstance(choice, dict)
        else getattr(choice, "finish_reason", "")
    )
    raw_tool_calls = (
        msg_dict.get("tool_calls", [])
        if isinstance(msg_dict, dict)
        else getattr(msg_dict, "tool_calls", [])
    ) or []
    tool_calls: list[dict[str, Any]] = []
    for raw_call in raw_tool_calls:
        if isinstance(raw_call, dict):
            call_data = raw_call
        elif hasattr(raw_call, "model_dump"):
            call_data = raw_call.model_dump()
        else:
            call_data = {
                "id": getattr(raw_call, "id", ""),
                "function": getattr(raw_call, "function", {}),
            }
        raw_function = call_data.get("function") or {}
        if not isinstance(raw_function, dict) and hasattr(raw_function, "model_dump"):
            raw_function = raw_function.model_dump()
        function = raw_function if isinstance(raw_function, dict) else {}
        raw_arguments = function.get("arguments") or {}
        if isinstance(raw_arguments, str):
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = {}
        else:
            arguments = raw_arguments
        if not isinstance(arguments, dict) or not function.get("name"):
            continue
        tool_calls.append(
            {
                "name": str(function["name"]),
                "args": arguments,
                "id": str(call_data.get("id") or ""),
                "type": "tool_call",
            }
        )

    usage = getattr(response, "usage", None) or response.get("usage", {}) or {}

    hidden = (
        getattr(response, "_hidden_params", None)
        or response.get("_hidden_params", {})
        or {}
    )
    actual_provider = str(
        provider_alias or hidden.get("custom_llm_provider", "") or "llm"
    )

    return AIMessage(
        content=content or "",
        tool_calls=tool_calls,
        usage_metadata={
            "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "output_tokens": int(usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        },
        response_metadata={
            "model_name": getattr(response, "model", None) or response.get("model", ""),
            "token_usage": dict(usage) if not isinstance(usage, dict) else usage,
            "provider": actual_provider,
            "model_id": str(hidden.get("model_id", "") or ""),
            "api_base_url": str(hidden.get("api_base", "") or ""),
            "finish_reason": finish_reason,
        },
    )


def strip_llm_reasoning_content(content: Any) -> Any:
    """Strip <think> tags while preserving normal content."""
    if isinstance(content, str):
        cleaned = _THINK_BLOCK_RE.sub("", content)
        return cleaned.strip()
    if isinstance(content, list):
        cleaned_blocks = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                new_block = dict(block)
                new_block["text"] = strip_llm_reasoning_content(new_block["text"])
                if new_block["text"]:
                    cleaned_blocks.append(new_block)
            elif isinstance(block, str):
                cleaned = strip_llm_reasoning_content(block)
                if cleaned:
                    cleaned_blocks.append(cleaned)
            else:
                cleaned_blocks.append(block)
        return cleaned_blocks
    return content


def sanitize_llm_response(response: Any) -> Any:
    """Best-effort response sanitizer for models that return visible thinking."""
    try:
        response.content = strip_llm_reasoning_content(response.content)
    except Exception:
        logger.debug("Failed to sanitize LLM response content")
    return response


def _preview_value(value: Any, limit: int = 50000) -> str:
    text = str(value)
    if len(text) > limit:
        return text[:limit] + "...[truncated]"
    return text


def _safe_attr(obj: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        try:
            value = getattr(obj, name, None)
        except Exception:
            value = None
        if value:
            return value
    return default


def _api_key_hint(llm: Any) -> str | None:
    key = _safe_attr(llm, "openai_api_key", "api_key", default=None)
    return _api_key_value_hint(key)


def _api_key_value_hint(key: Any) -> str | None:
    if not key:
        return None
    value = getattr(key, "get_secret_value", lambda: str(key))()
    return sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _object_field(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    try:
        return getattr(obj, name, default)
    except Exception:
        return default


@dataclass(frozen=True)
class _ResolvedRouterDeployment:
    provider_alias: str
    model_name: str
    api_base_url: str
    api_key: Any


def _resolve_router_response_deployment(
    router: Any, response: Any
) -> _ResolvedRouterDeployment | None:
    """Resolve the exact deployment selected by LiteLLM from response metadata."""

    hidden = getattr(response, "_hidden_params", None)
    if not isinstance(hidden, dict):
        return None
    model_id = hidden.get("model_id")
    get_deployment = getattr(router, "get_deployment", None)
    if not isinstance(model_id, str) or not model_id or not callable(get_deployment):
        return None
    try:
        deployment = get_deployment(model_id)
    except Exception:
        return None
    if deployment is None:
        return None

    model_info = _object_field(deployment, "model_info", {})
    litellm_params = _object_field(deployment, "litellm_params", {})
    return _ResolvedRouterDeployment(
        provider_alias=str(_object_field(model_info, "provider_alias", "") or ""),
        model_name=str(_object_field(litellm_params, "model", "") or ""),
        api_base_url=str(
            _object_field(litellm_params, "api_base", "")
            or hidden.get("api_base", "")
            or ""
        ),
        api_key=_object_field(litellm_params, "api_key"),
    )


def _unwrap_bound_llm(llm: Any) -> tuple[Any, dict[str, Any]]:
    """Return the underlying model and all kwargs applied by ``bind_tools``."""

    current = llm
    bound_kwargs: dict[str, Any] = {}
    while isinstance(current, RunnableBinding):
        bound_kwargs = {**dict(current.kwargs), **bound_kwargs}
        current = current.bound
    return current, bound_kwargs


class AuditedChatModel(BaseChatModel):
    """Tool-bindable async chat model that uses the canonical audit wrapper."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    inner: Any

    @property
    def _llm_type(self) -> str:
        return "academic-cluster-audited"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Callable[..., Any] | BaseTool],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, AIMessage]:
        bind_kwargs = dict(kwargs)
        if tool_choice is not None:
            bind_kwargs["tool_choice"] = tool_choice
        return type(self)(inner=self.inner.bind_tools(tools, **bind_kwargs))

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del messages, stop, run_manager, kwargs
        raise RuntimeError("AuditedChatModel supports asynchronous invocation only")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del run_manager
        if stop:
            kwargs["stop"] = stop
        response = await ainvoke_with_callbacks(self.inner, messages, **kwargs)
        if not isinstance(response, BaseMessage):
            raise TypeError("audited chat model returned a non-message response")
        return ChatResult(generations=[ChatGeneration(message=response)])


def _get_llm_request_gate() -> tuple[BoundedFifoGate, float]:
    """Return the explicit LLM capacity boundary configured by the operator.

    Provider RPM is a rate budget, not a measure of safe open connections.  The
    application therefore uses an independently configured in-flight capacity
    plus a bounded FIFO queue. LiteLLM remains responsible for provider RPM,
    TPM, cooldown, and failover after work is admitted here.
    """

    global _llm_request_gate, _llm_request_gate_config

    from ..config import get_settings

    settings = get_settings()
    config = (
        settings.llm_max_concurrent_requests,
        settings.llm_max_queued_requests,
        settings.llm_queue_wait_timeout_seconds,
    )
    if _llm_request_gate is None or config != _llm_request_gate_config:
        _llm_request_gate = BoundedFifoGate(capacity=config[0], max_waiters=config[1])
        _llm_request_gate_config = config
        logger.info(
            "LLM request gate configured",
            capacity=config[0],
            max_waiters=config[1],
            queue_wait_timeout_seconds=config[2],
        )
    return _llm_request_gate, config[2]


@asynccontextmanager
async def _llm_request_slot() -> AsyncIterator[None]:
    """Acquire the bounded LLM queue without consuming provider call timeout."""

    gate, wait_timeout = _get_llm_request_gate()
    async with gate.slot(timeout=wait_timeout):
        yield


# 轮询计数器
_rr_counter = 0


def create_llm(
    temperature: float = 0.7,
    max_tokens: int | None = None,
    task: str = "default",
) -> ChatOpenAI:
    """
    从 Provider Pool 创建 ChatOpenAI 实例。

    使用加权轮询选择 provider，每次调用可能返回不同 provider 的客户端。
    模型名始终使用 provider 自身配置（不同 provider 模型不通用）。

    Args:
        temperature: 温度参数
        max_tokens: 最大 token 数
        task: 任务标签，用于 visibility 过滤（默认 "default" 仅匹配 public）

    Returns:
        ChatOpenAI 实例
    """
    global _rr_counter

    from .provider_pool import get_llm_pool

    pool = get_llm_pool()
    deployments = pool.deployments

    if not deployments:
        raise RuntimeError("No LLM deployments configured")

    # visibility 过滤
    allowed = _TASK_TAGS.get(task, {"public"})
    candidates = [
        d for d in deployments
        if set(d.get("model_info", {}).get("visibility", ["public"])) & allowed
    ]
    if not candidates:
        candidates = deployments  # fallback 全池

    # 轮询选择
    _rr_counter = (_rr_counter + 1) % len(candidates)
    deployment = candidates[_rr_counter]
    params = deployment["litellm_params"]
    routing_policy = pool.routing_policy
    if routing_policy is None:
        raise RuntimeError("LLM pool is missing its runtime routing policy")

    # 始终使用 provider 自身配置的模型名（不同 provider 模型不通用）
    litellm_model = params["model"]
    actual_model = litellm_model.replace("openai/", "", 1)

    llm = ChatOpenAI(
        model=actual_model,
        temperature=temperature,
        api_key=params["api_key"],
        base_url=params.get("api_base"),
        max_tokens=max_tokens,  # type: ignore[call-arg]
        timeout=routing_policy.provider_request_timeout_seconds,
    )
    # 在 llm 对象上附加 provider 别名和路由分组名，供 ainvoke_with_callbacks 读取
    model_info = deployment.get("model_info", {}) or {}
    llm._litellm_model = deployment.get(  # type: ignore[attr-defined]
        "model_name", actual_model
    )  # 路由分组名（如 "Qwen3-8B"），传给 Router
    llm._provider_alias = model_info.get("provider_alias", "") or deployment.get(  # type: ignore[attr-defined]
        "model_name", ""
    )
    llm._provider_rpm_limit = int(  # type: ignore[attr-defined]
        params.get("rpm") or routing_policy.provider_default_rpm
    )
    llm._routing_policy = routing_policy  # type: ignore[attr-defined]
    llm._requested_model = actual_model  # type: ignore[attr-defined]
    llm._upstream_model = actual_model  # type: ignore[attr-defined]
    llm._api_base_url = params.get("api_base")  # type: ignore[attr-defined]
    llm._temperature = temperature  # type: ignore[attr-defined]
    llm._max_tokens = max_tokens  # type: ignore[attr-defined]

    return llm


async def ainvoke_with_callbacks(
    llm: Any,
    input: Any,
    config: Any = None,
    timeout: float | None = None,
    **kwargs: Any,
) -> Any:
    """
    包装 LLM 调用，手动追踪 token 用量和持久化到 DB。

    通过 LiteLLM Router 发出实际 HTTP 请求，由 Router 处理：
    - 多端点加权路由（simple-shuffle）
    - 有界重试 + 故障转移（Router num_retries=1）
    - RPM/TPM 限速
    - 不健康端点 cooldown（allowed_fails=3, cooldown_time=60s）

    LangChain 的 callback 系统对 ChatOpenAI 的 on_llm_end 不可靠，
    因此在此处直接追踪。

    使用方式:
        llm = create_llm()
        response = await ainvoke_with_callbacks(llm, messages)
    """
    import asyncio
    import time as _time

    from .observability import (
        get_current_agent_phase,
        get_current_execution,
        get_current_project,
    )

    start_time = _time.monotonic()
    base_llm, bound_kwargs = _unwrap_bound_llm(llm)
    routing_policy = getattr(base_llm, "_routing_policy", None)
    if routing_policy is None:
        routing_policy = _default_routing_policy()
    effective_timeout = float(
        timeout
        if timeout is not None
        else routing_policy.provider_request_timeout_seconds
    )
    project_id = get_current_project()
    execution_id = get_current_execution()
    agent_phase = get_current_agent_phase()
    node_name = agent_phase or ("agent" if execution_id else "unknown")
    if not project_id or not execution_id:
        logger.warning(
            "ainvoke_with_callbacks has no audit execution context",
            node=node_name,
            has_project=project_id is not None,
            has_execution=execution_id is not None,
        )

    _temperature = getattr(base_llm, "_temperature", 0.7)
    _max_tokens = getattr(base_llm, "_max_tokens", None)

    provider_alias = getattr(base_llm, "_provider_alias", "") or "llm"
    requested_model = (
        getattr(base_llm, "_requested_model", None)
        or _safe_attr(base_llm, "model_name", "model", default=None)
        or "unknown"
    )
    upstream_model = getattr(base_llm, "_upstream_model", None) or requested_model
    api_base_url = getattr(base_llm, "_api_base_url", None) or str(
        _safe_attr(base_llm, "openai_api_base", "base_url", default="") or ""
    )
    api_key_hint = _api_key_hint(base_llm)
    litellm_model = getattr(base_llm, "_litellm_model", "openai/" + requested_model)
    call_id = None
    db = None
    invoke_task: asyncio.Task[Any] | None = None

    if project_id and execution_id:
        try:
            from .database import get_database

            db = get_database()
            call_id = await db.create_llm_call(
                pipeline_run_id=None,
                node_execution_id=None,
                project_id=project_id,
                execution_id=execution_id,
                node_name=node_name,
                call_type="llm",
                provider_name=provider_alias,
                model_name=requested_model,
                requested_model=requested_model,
                upstream_model=upstream_model,
                api_base_url=api_base_url,
                api_key_hint=api_key_hint,
                status="running",
                input_preview=_preview_value(input),
                request_metadata={
                    "node_name": node_name,
                    "timeout_s": effective_timeout,
                    "temperature": _temperature,
                    "max_tokens": _max_tokens,
                    "provider_alias": provider_alias,
                    "execution_id": execution_id,
                    "agent_phase": agent_phase,
                    "config_keys": sorted((config or {}).keys())
                    if isinstance(config, dict)
                    else [],
                },
            )
        except Exception as e:
            logger.warning(
                "Failed to create llm_call audit row", error=str(e), node=node_name
            )

    # 通过 LiteLLM Router 发送请求（Router 内置 retry + failover）
    from .provider_pool import get_llm_pool

    try:
        pool = get_llm_pool()
    except RuntimeError:
        pool = None

    try:
        if pool is not None:
            messages = _messages_to_openai(input)
            router = pool.router
            router_kwargs = {**bound_kwargs, **kwargs}
            router_kwargs.pop("config", None)

            max_retries = routing_policy.provider_timeout_retries
            last_timeout_error = None
            for attempt in range(max_retries):
                try:
                    async with _llm_request_slot():
                        # 使用 asyncio.wait 替代 wait_for——wait_for 无法取消 httpx
                        invoke_task = asyncio.create_task(
                            router.acompletion(
                                model=litellm_model,
                                messages=messages,
                                temperature=_temperature,
                                max_tokens=_max_tokens,
                                timeout=effective_timeout,
                                frequency_penalty=0.5,
                                **router_kwargs,
                            )
                        )
                        _done, _ = await asyncio.wait(
                            [invoke_task],
                            timeout=(
                                effective_timeout
                                + routing_policy.provider_timeout_grace_seconds
                            ),
                        )
                        if _done:
                            completed_task = invoke_task
                            assert completed_task is not None
                            invoke_task = None
                            response = completed_task.result()
                        else:
                            await _cancel_and_wait(invoke_task)
                            invoke_task = None
                            raise TimeoutError(
                                "LLM call timed out after "
                                f"{effective_timeout + routing_policy.provider_timeout_grace_seconds}s"
                            )
                    break  # success
                except TimeoutError as te:
                    last_timeout_error = te
                    if attempt < max_retries - 1:
                        wait_s = (
                            routing_policy.provider_retry_delay_seconds
                            + secrets.randbelow(501) / 1000
                        )
                        logger.warning(
                            "LLM call timed out, retrying",
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            wait_s=wait_s,
                            node=node_name,
                        )
                        await asyncio.sleep(wait_s)
                    else:
                        raise last_timeout_error from None

            resolved_deployment = _resolve_router_response_deployment(router, response)
            if resolved_deployment is not None:
                provider_alias = resolved_deployment.provider_alias or provider_alias
                api_base_url = resolved_deployment.api_base_url or api_base_url
                api_key_hint = (
                    _api_key_value_hint(resolved_deployment.api_key) or api_key_hint
                )
                if resolved_deployment.model_name:
                    upstream_model = resolved_deployment.model_name
            response = _router_response_to_aimessage(response, provider_alias)
            response = sanitize_llm_response(response)
        else:
            # Fallback: 直接使用 llm.ainvoke()（测试环境未初始化 pool 时）
            async with _llm_request_slot():
                invoke_task = asyncio.create_task(
                    llm.ainvoke(input, config=config, **kwargs)
                )
                _done, _ = await asyncio.wait([invoke_task], timeout=effective_timeout)
                if _done:
                    completed_task = invoke_task
                    assert completed_task is not None
                    invoke_task = None
                    response = completed_task.result()
                    response = sanitize_llm_response(response)
                else:
                    await _cancel_and_wait(invoke_task)
                    invoke_task = None
                    raise TimeoutError(f"LLM call timed out after {effective_timeout}s")

    except asyncio.CancelledError:
        await _cancel_and_wait(invoke_task)
        invoke_task = None
        elapsed_ms = int((_time.monotonic() - start_time) * 1000)
        err_msg = "LLM call cancelled"
        if db and call_id:
            try:
                await db.finish_llm_call(
                    call_id=call_id,
                    status="error",
                    error_message=err_msg,
                    latency_ms=elapsed_ms,
                )
            except Exception as e:
                logger.warning(
                    "Failed to persist llm_call cancellation",
                    error=str(e),
                    node=node_name,
                )
        logger.warning(err_msg, node=node_name)
        raise
    except Exception as e:
        elapsed_ms = int((_time.monotonic() - start_time) * 1000)
        is_timeout = isinstance(e, asyncio.TimeoutError)
        err_msg = (
            f"LLM call timed out after {effective_timeout}s" if is_timeout else str(e)
        )
        if db and call_id:
            try:
                await db.finish_llm_call(
                    call_id=call_id,
                    status="error",
                    error_message=err_msg,
                    latency_ms=elapsed_ms,
                )
            except Exception as persist_error:
                logger.warning(
                    "Failed to persist llm_call error",
                    error=str(persist_error),
                    node=node_name,
                )
        logger.error(
            err_msg,
            node=node_name,
            timeout_s=effective_timeout,
            elapsed_ms=elapsed_ms,
        )
        raise

    elapsed_ms = int((_time.monotonic() - start_time) * 1000)

    # 提取 token 用量
    prompt_tokens = 0
    completion_tokens = 0
    model_name = "unknown"

    usage_meta = getattr(response, "usage_metadata", None)
    if usage_meta:
        prompt_tokens = usage_meta.get("input_tokens", 0) or usage_meta.get(
            "prompt_tokens", 0
        )
        completion_tokens = usage_meta.get("output_tokens", 0) or usage_meta.get(
            "completion_tokens", 0
        )

    resp_meta = getattr(response, "response_metadata", None)
    if resp_meta:
        model_name = resp_meta.get("model_name", "unknown")
        token_usage = resp_meta.get("token_usage", {})
        if token_usage and not prompt_tokens:
            prompt_tokens = token_usage.get("prompt_tokens", 0)
            completion_tokens = token_usage.get("completion_tokens", 0)

    if model_name == "unknown":
        model_name = requested_model
    upstream_model = model_name

    # 计算 cost
    cost = 0.0
    input_price = 0.0
    output_price = 0.0
    try:
        from .database import get_database

        _db = get_database()
        from ..api.admin.providers import get_provider_pricing

        input_price, output_price = await get_provider_pricing(
            _db, provider_alias, model_name
        )
        if input_price or output_price:
            cost = (
                prompt_tokens * input_price + completion_tokens * output_price
            ) / 1_000_000
    except Exception:  # nosec B110
        pass

    if db and call_id:
        try:
            await db.finish_llm_call(
                call_id=call_id,
                status="success",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                latency_ms=elapsed_ms,
                output_preview=_preview_value(getattr(response, "content", "")),
                model_name=model_name,
                upstream_model=upstream_model,
                provider_name=provider_alias,
                api_base_url=api_base_url,
                api_key_hint=api_key_hint,
                input_price_per_m=input_price,
                output_price_per_m=output_price,
            )
        except Exception as e:
            logger.warning(
                "Failed to finish llm_call audit row", error=str(e), node=node_name
            )

    return response


def create_llm_with_retry(
    temperature: float = 0.7,
    max_tokens: int | None = None,
    task: str = "default",
    max_retries: int = 3,
) -> Any:
    """
    创建带重试的 LLM 调用包装器。

    每次重试使用不同的 provider（轮询），实现故障转移。

    Returns:
        async callable: _invoke(messages) -> response
    """

    async def _invoke(messages: Any) -> Any:
        from tenacity import (
            retry,
            stop_after_attempt,
            wait_exponential,
        )

        @retry(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=2, min=3, max=30),
            reraise=True,
        )
        async def _call() -> Any:
            llm = create_llm(temperature=temperature, max_tokens=max_tokens, task=task)
            return await ainvoke_with_callbacks(llm, messages)

        return await _call()

    return _invoke


async def invoke_llm(
    messages: list[Any],
    temperature: float = 0.7,
    max_tokens: int | None = None,
    task: str = "default",
) -> Any:
    """
    便捷函数：创建 LLM 并调用，自动注入 callback。

    Returns:
        LLM response
    """
    llm = create_llm(temperature=temperature, max_tokens=max_tokens, task=task)
    return await ainvoke_with_callbacks(llm, messages)
