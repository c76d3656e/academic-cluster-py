"""
统一 LLM 客户端工厂

通过 Provider Pool 创建 ChatOpenAI 实例，支持多端点负载均衡。
所有 agent 和 node 应通过此模块获取 LLM 客户端。
"""

import asyncio
import re
from typing import Optional

import structlog
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()

_rr_counter = 0
_llm_queue_semaphore: asyncio.Semaphore | None = None
_llm_queue_capacity = 0

_THINK_BLOCK_RE = re.compile(r"<think\b[^>]*>.*?(?:</think>|$)", re.IGNORECASE | re.DOTALL)
_REASONING_BLOCK_RE = re.compile(
    r"^\s*(?:analysis|reasoning|thought|思考|推理)\s*[:：].*?(?=\n\n|$)",
    re.IGNORECASE | re.DOTALL | re.MULTILINE,
)


def strip_llm_reasoning_content(content):
    """Strip provider-visible reasoning blocks while preserving normal content."""
    if isinstance(content, str):
        cleaned = _THINK_BLOCK_RE.sub("", content)
        cleaned = _REASONING_BLOCK_RE.sub("", cleaned)
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


def sanitize_llm_response(response):
    """Best-effort response sanitizer for models that return visible thinking."""
    try:
        response.content = strip_llm_reasoning_content(response.content)
    except Exception:
        logger.debug("Failed to sanitize LLM response content")
    return response


def _get_llm_queue_semaphore() -> asyncio.Semaphore:
    """Build a process-local queue gate from enabled provider capacity."""
    global _llm_queue_semaphore, _llm_queue_capacity

    from .provider_pool import get_llm_available_slots

    capacity = get_llm_available_slots(default=10)
    if _llm_queue_semaphore is None or capacity != _llm_queue_capacity:
        _llm_queue_capacity = capacity
        _llm_queue_semaphore = asyncio.Semaphore(capacity)
        logger.info("LLM queue capacity resolved", capacity=capacity)
    return _llm_queue_semaphore

# 轮询计数器
_rr_counter = 0


def create_llm(
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
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
        max_tokens=max_tokens,
        timeout=180,  # 单次 HTTP 请求超时 3 分钟
    )
    # 在 llm 对象上附加 provider 别名，供 ainvoke_with_callbacks 读取
    llm._provider_alias = deployment.get("model_name", "")
    llm._provider_rpm_limit = int(params.get("rpm") or 10)

    return llm


async def ainvoke_with_callbacks(llm, input, config=None, timeout: float = 300.0, **kwargs):
    """
    包装 LLM ainvoke 调用，手动追踪 token 用量和持久化到 DB。

    LangChain 的 callback 系统对 ChatOpenAI 的 on_llm_end 不可靠，
    因此在此处直接追踪。

    使用方式:
        llm = create_llm()
        response = await ainvoke_with_callbacks(llm, messages)
    """
    import asyncio
    import time as _time

    from .observability import get_current_node, get_current_tracker

    start_time = _time.monotonic()
    node_name = get_current_node() or "unknown"
    tracker = get_current_tracker()

    try:
        semaphore = _get_llm_queue_semaphore()
        async with semaphore:
            response = await asyncio.wait_for(llm.ainvoke(input, config=config, **kwargs), timeout=timeout)
            response = sanitize_llm_response(response)
    except asyncio.TimeoutError:
        logger.error("LLM call timed out", node=node_name, timeout_s=timeout)
        raise TimeoutError(f"LLM call timed out after {timeout}s")

    elapsed_ms = int((_time.monotonic() - start_time) * 1000)

    # 提取 token 用量
    prompt_tokens = 0
    completion_tokens = 0
    model_name = "unknown"

    usage_meta = getattr(response, "usage_metadata", None)
    if usage_meta:
        prompt_tokens = usage_meta.get("input_tokens", 0) or usage_meta.get("prompt_tokens", 0)
        completion_tokens = usage_meta.get("output_tokens", 0) or usage_meta.get("completion_tokens", 0)

    resp_meta = getattr(response, "response_metadata", None)
    if resp_meta:
        model_name = resp_meta.get("model_name", "unknown")
        # OpenAI 格式 token_usage
        token_usage = resp_meta.get("token_usage", {})
        if token_usage and not prompt_tokens:
            prompt_tokens = token_usage.get("prompt_tokens", 0)
            completion_tokens = token_usage.get("completion_tokens", 0)

    # 从 llm 对象获取真实的 provider 别名（如 "gitee"、"siliconflow"）
    provider_alias = getattr(llm, "_provider_alias", "") or "llm"

    # 按当前定价计算 cost（使用真实的 provider 别名匹配数据库定价）
    cost = 0.0
    try:
        from .database import get_database
        _db = get_database()
        from ..api.admin.providers import get_provider_pricing
        input_price, output_price = await get_provider_pricing(_db, provider_alias, model_name)
        if input_price or output_price:
            cost = (prompt_tokens * input_price + completion_tokens * output_price) / 1_000_000
    except Exception:
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
        except Exception:
            pass

    # 持久化到 DB
    if tracker and tracker.run_id:
        try:
            from .database import get_database
            db = get_database()
            exec_id = tracker._node_ids.get(node_name)
            if exec_id:
                call_id = await db.create_llm_call(
                    pipeline_run_id=tracker.run_id,
                    node_execution_id=exec_id,
                    call_type="llm",
                    provider_name=provider_alias,
                    model_name=model_name,
                    latency_ms=elapsed_ms,
                )
                await db.finish_llm_call(
                    call_id=call_id,
                    status="success",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    cost=cost,
                    latency_ms=elapsed_ms,
                )
        except Exception as e:
            logger.warning("Failed to persist llm_call", error=str(e))

    return response


def create_llm_with_retry(
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    max_retries: int = 3,
):
    """
    创建带重试的 LLM 调用包装器。

    每次重试使用不同的 provider（轮询），实现故障转移。

    Returns:
        async callable: _invoke(messages) -> response
    """
    async def _invoke(messages):
        from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

        @retry(
            stop=stop_after_attempt(max_retries),
            wait=wait_exponential(multiplier=2, min=3, max=30),
            reraise=True,
        )
        async def _call():
            llm = create_llm(temperature=temperature, max_tokens=max_tokens)
            return await ainvoke_with_callbacks(llm, messages)

        return await _call()

    return _invoke


async def invoke_llm(
    messages: list,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
):
    """
    便捷函数：创建 LLM 并调用，自动注入 callback。

    Returns:
        LLM response
    """
    llm = create_llm(temperature=temperature, max_tokens=max_tokens)
    return await ainvoke_with_callbacks(llm, messages)
