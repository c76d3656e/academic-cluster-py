"""
统一 LLM 客户端工厂

通过 Provider Pool 创建 ChatOpenAI 实例，支持多端点负载均衡。
所有 agent 和 node 应通过此模块获取 LLM 客户端。
"""

from typing import Optional

import structlog
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()

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
    )

    return llm


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
            return await llm.ainvoke(messages)

        return await _call()

    return _invoke
