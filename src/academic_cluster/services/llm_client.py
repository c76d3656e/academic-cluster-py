"""
统一 LLM 客户端工厂

通过 LiteLLM Router 发出所有 LLM 请求，由 Router 处理路由、重试、
故障转移、RPM 限速和 cooldown。

所有 agent 和 node 应通过此模块获取 LLM 客户端。
"""

import asyncio
import re
from hashlib import sha256
from typing import Any

import structlog
from langchain_core.messages import AIMessage
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()

_rr_counter = 0
_llm_queue_semaphore: asyncio.Semaphore | None = None
_llm_queue_capacity = 0

_THINK_BLOCK_RE = re.compile(
    r"<think\b[^>]*>.*?(?:</think>|$)", re.IGNORECASE | re.DOTALL
)


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

    usage = getattr(response, "usage", None) or response.get("usage", {}) or {}

    hidden = (
        getattr(response, "_hidden_params", None)
        or response.get("_hidden_params", {})
        or {}
    )
    actual_provider = str(
        hidden.get("model_id", "") or hidden.get("api_base", "") or provider_alias
    )

    return AIMessage(
        content=content or "",
        usage_metadata={
            "input_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "output_tokens": int(usage.get("completion_tokens", 0) or 0),
            "total_tokens": int(usage.get("total_tokens", 0) or 0),
        },
        response_metadata={
            "model_name": getattr(response, "model", None) or response.get("model", ""),
            "token_usage": dict(usage) if not isinstance(usage, dict) else usage,
            "provider": actual_provider,
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
    if not key:
        return None
    value = getattr(key, "get_secret_value", lambda: str(key))()
    return sha256(str(value).encode("utf-8")).hexdigest()[:12]


def _get_llm_queue_semaphore() -> asyncio.Semaphore:
    """Build a process-local queue gate from enabled provider capacity.

    容量 = 所有 provider 总 slots × 并发管道倍数（默认 3 倍），
    避免跨 pipeline 竞争导致死锁。
    """
    global _llm_queue_semaphore, _llm_queue_capacity

    from .provider_pool import get_llm_available_slots

    base = get_llm_available_slots(default=10)
    capacity = max(10, base * 3)  # 总 slot × 3 倍余量，容纳多个 pipeline
    if _llm_queue_semaphore is None or capacity != _llm_queue_capacity:
        _llm_queue_capacity = capacity
        _llm_queue_semaphore = asyncio.Semaphore(capacity)
        logger.info("LLM queue capacity resolved", capacity=capacity, base_slots=base)
    return _llm_queue_semaphore


# 轮询计数器
_rr_counter = 0


def create_llm(
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> ChatOpenAI:
    """
    从 Provider Pool 创建 ChatOpenAI 实例。

    使用加权轮询选择 provider，每次调用可能返回不同 provider 的客户端。
    模型名始终使用 provider 自身配置（不同 provider 模型不通用）。

    Args:
        temperature: 温度参数
        max_tokens: 最大 token 数

    Returns:
        ChatOpenAI 实例
    """
    global _rr_counter

    from .provider_pool import get_llm_pool

    pool = get_llm_pool()
    deployments = pool.deployments

    if not deployments:
        raise RuntimeError("No LLM deployments configured")

    # 轮询选择
    _rr_counter = (_rr_counter + 1) % len(deployments)
    deployment = deployments[_rr_counter]
    params = deployment["litellm_params"]

    # 始终使用 provider 自身配置的模型名（不同 provider 模型不通用）
    litellm_model = params["model"]
    actual_model = litellm_model.replace("openai/", "", 1)

    llm = ChatOpenAI(
        model=actual_model,
        temperature=temperature,
        api_key=params["api_key"],
        base_url=params.get("api_base"),
        max_tokens=max_tokens,  # type: ignore[call-arg]
        timeout=300,  # 单次 HTTP 请求超时 5 分钟
    )
    # 在 llm 对象上附加 provider 别名和路由分组名，供 ainvoke_with_callbacks 读取
    model_info = deployment.get("model_info", {}) or {}
    llm._litellm_model = deployment.get(  # type: ignore[attr-defined]
        "model_name", actual_model
    )  # 路由分组名（如 "Qwen3-8B"），传给 Router
    llm._provider_alias = model_info.get("provider_alias", "") or deployment.get(  # type: ignore[attr-defined]
        "model_name", ""
    )
    llm._provider_rpm_limit = int(params.get("rpm") or 10)  # type: ignore[attr-defined]
    llm._requested_model = actual_model  # type: ignore[attr-defined]
    llm._upstream_model = actual_model  # type: ignore[attr-defined]
    llm._api_base_url = params.get("api_base")  # type: ignore[attr-defined]
    llm._temperature = temperature  # type: ignore[attr-defined]
    llm._max_tokens = max_tokens  # type: ignore[attr-defined]

    return llm


async def ainvoke_with_callbacks(
    llm: Any, input: Any, config: Any = None, timeout: float = 300.0, **kwargs: Any
) -> Any:
    """
    包装 LLM 调用，手动追踪 token 用量和持久化到 DB。

    通过 LiteLLM Router 发出实际 HTTP 请求，由 Router 处理：
    - 多端点加权路由（simple-shuffle）
    - 失败自动重试 + 故障转移（num_retries=2）
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
        get_current_node,
        get_current_project,
        get_current_tracker,
        get_resolved_run_id,
    )

    start_time = _time.monotonic()
    node_name = get_current_node() or "unknown"
    tracker = get_current_tracker()
    run_id = get_resolved_run_id()
    if not run_id:
        logger.warning(
            "ainvoke_with_callbacks no run_id",
            node=node_name,
            has_tracker=tracker is not None,
        )

    _temperature = getattr(llm, "_temperature", 0.7)
    _max_tokens = getattr(llm, "_max_tokens", None)

    provider_alias = getattr(llm, "_provider_alias", "") or "llm"
    requested_model = (
        getattr(llm, "_requested_model", None)
        or _safe_attr(llm, "model_name", "model", default=None)
        or "unknown"
    )
    upstream_model = getattr(llm, "_upstream_model", None) or requested_model
    api_base_url = getattr(llm, "_api_base_url", None) or str(
        _safe_attr(llm, "openai_api_base", "base_url", default="") or ""
    )
    litellm_model = getattr(llm, "_litellm_model", "openai/" + requested_model)
    call_id = None
    db = None

    if run_id:
        try:
            from .database import get_database

            db = get_database()
            exec_id = tracker._node_ids.get(node_name) if tracker else None
            if not exec_id:
                exec_id = await db.create_node_execution(
                    run_id,
                    node_name,
                    "llm",
                )
                if tracker:
                    tracker._node_ids[node_name] = exec_id
            call_id = await db.create_llm_call(
                pipeline_run_id=run_id,
                node_execution_id=exec_id,
                project_id=get_current_project()
                or getattr(tracker, "project_id", None),
                node_name=node_name,
                call_type="llm",
                provider_name=provider_alias,
                model_name=requested_model,
                requested_model=requested_model,
                upstream_model=upstream_model,
                api_base_url=api_base_url,
                api_key_hint=_api_key_hint(llm),
                status="running",
                input_preview=_preview_value(input),
                request_metadata={
                    "node_name": node_name,
                    "timeout_s": timeout,
                    "temperature": _temperature,
                    "max_tokens": _max_tokens,
                    "provider_alias": provider_alias,
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
            semaphore = _get_llm_queue_semaphore()
            router_kwargs = dict(kwargs)
            router_kwargs.pop("config", None)

            async with semaphore:
                response = await asyncio.wait_for(
                    pool.router.acompletion(
                        model=litellm_model,
                        messages=messages,
                        temperature=_temperature,
                        max_tokens=_max_tokens,
                        timeout=timeout,
                        frequency_penalty=0.5,
                        **router_kwargs,
                    ),
                    timeout=timeout + 60,
                )

            response = _router_response_to_aimessage(response, provider_alias)
            response = sanitize_llm_response(response)
        else:
            # Fallback: 直接使用 llm.ainvoke()（测试环境未初始化 pool 时）
            semaphore = _get_llm_queue_semaphore()
            async with semaphore:
                response = await asyncio.wait_for(
                    llm.ainvoke(input, config=config, **kwargs), timeout=timeout
                )
                response = sanitize_llm_response(response)

    except asyncio.CancelledError:
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
        err_msg = f"LLM call timed out after {timeout}s" if is_timeout else str(e)
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
        logger.error(err_msg, node=node_name, timeout_s=timeout, elapsed_ms=elapsed_ms)
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

    # 记录到 tracker
    if tracker:
        try:
            await tracker.token_tracker.record(
                node_name=node_name,
                provider_name=provider_alias,
                model_name=model_name,
                call_type="llm",
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost=cost,
                latency_ms=elapsed_ms,
            )
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
            llm = create_llm(temperature=temperature, max_tokens=max_tokens)
            return await ainvoke_with_callbacks(llm, messages)

        return await _call()

    return _invoke


async def invoke_llm(
    messages: list[Any],
    temperature: float = 0.7,
    max_tokens: int | None = None,
) -> Any:
    """
    便捷函数：创建 LLM 并调用，自动注入 callback。

    Returns:
        LLM response
    """
    llm = create_llm(temperature=temperature, max_tokens=max_tokens)
    return await ainvoke_with_callbacks(llm, messages)
