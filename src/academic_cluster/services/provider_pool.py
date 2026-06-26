"""
Provider Pool - 基于 LiteLLM Router 的多端点负载均衡

LLM / Embedding 使用 LiteLLM Router（内置 RPM 限速、故障转移、加权轮询）。
Rerank 使用轻量自定义 pool（LiteLLM 不原生支持 SiliconFlow rerank）。
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import structlog

logger = structlog.get_logger()


# =============================================================================
# LiteLLM Router Pool（用于 LLM 和 Embedding）
# =============================================================================


class LiteLLMPool:
    """
    基于 LiteLLM Router 的 Provider Pool。

    支持：
    - 多端点加权轮询
    - RPM/TPM 限速（enable_pre_call_checks）
    - 自动故障转移 + 重试
    - 健康检查 + cooldown
    """

    def __init__(
        self, service_name: str, model_list: list[dict[str, Any]], **router_kwargs: Any
    ) -> None:
        self.service_name = service_name
        self._model_list = model_list
        self._router_kwargs = router_kwargs
        self._router: Any = None

    def _ensure_router(self) -> None:
        """延迟初始化 Router（避免导入时就需要 litellm）"""
        if self._router is not None:
            return

        from litellm import Router

        self._router = Router(
            model_list=self._model_list,
            routing_strategy="simple-shuffle",
            num_retries=3,
            timeout=300,
            retry_after=2,
            enable_pre_call_checks=False,
            disable_cooldowns=True,
            **self._router_kwargs,
        )
        logger.info(
            "LiteLLM Router initialized",
            service=self.service_name,
            deployments=len(self._model_list),
        )

    @property
    def router(self) -> Any:
        self._ensure_router()
        return self._router

    def get_first_deployment(self) -> dict[str, Any]:
        """获取第一个部署的配置（用于创建 ChatOpenAI 等 LangChain 客户端）"""
        if not self._model_list:
            raise RuntimeError(f"No deployments in {self.service_name} pool")
        result: dict[str, Any] = self._model_list[0]["litellm_params"]
        return result

    def get_model_name(self) -> str:
        """获取模型别名"""
        if not self._model_list:
            raise RuntimeError(f"No deployments in {self.service_name} pool")
        return str(self._model_list[0]["model_name"])

    @property
    def deployments(self) -> list[dict[str, Any]]:
        """获取所有部署配置"""
        return self._model_list

    def get_total_rpm_limit(self, default_per_deployment: int = 10) -> int:
        """Return the summed configured RPM budget for this pool."""
        total = 0
        for deployment in self._model_list:
            params = deployment.get("litellm_params", {})
            try:
                rpm = int(params.get("rpm") or default_per_deployment)
            except (TypeError, ValueError):
                rpm = default_per_deployment
            total += max(1, rpm)
        return max(1, total)

    def get_stats(self) -> dict[str, Any]:
        """获取池统计"""
        return {
            "service": self.service_name,
            "deployments": len(self._model_list),
            "models": [d["model_name"] for d in self._model_list],
        }


# =============================================================================
# Rerank Pool（自定义，LiteLLM 不支持 SiliconFlow rerank）
# =============================================================================


class RerankProvider:
    """单个 Rerank 端点"""

    def __init__(
        self,
        name: str,
        model: str,
        api_url: str,
        api_key: str,
        rpm_limit: int = 10,
        priority: int = 1,
    ):
        self.name = name
        self.model = model
        self.api_url = api_url
        self.api_key = api_key
        self.rpm_limit = rpm_limit
        self.priority = priority
        self.is_healthy = True
        self.error_count = 0
        self.request_count = 0
        self._semaphore = asyncio.Semaphore(rpm_limit)
        self._lock = asyncio.Lock()


class RerankPool:
    """Rerank 负载均衡池（加权轮询 + 故障转移）"""

    def __init__(self, providers: list[RerankProvider]):
        self._providers = providers
        if not providers:
            raise ValueError("RerankPool requires at least one provider")

    async def execute(
        self, func: Callable[[RerankProvider], Any], max_retries: int | None = None
    ) -> Any:
        """选一个 provider 执行 func(provider)，自动重试故障转移"""
        import random

        if max_retries is None:
            max_retries = len(self._providers)

        last_error = None
        for attempt in range(max_retries):
            healthy = [p for p in self._providers if p.is_healthy]
            if not healthy:
                for p in self._providers:
                    p.is_healthy = True
                    p.error_count = 0
                healthy = self._providers

            weights = [1.0 / p.priority for p in healthy]
            provider = random.choices(healthy, weights=weights, k=1)[0]  # nosec B311

            try:
                async with provider._semaphore:
                    result = await func(provider)

                async with provider._lock:
                    provider.request_count += 1
                    provider.error_count = 0
                    provider.is_healthy = True

                return result

            except Exception as e:
                last_error = e
                async with provider._lock:
                    provider.error_count += 1
                    if provider.error_count >= 3:
                        provider.is_healthy = False
                        logger.warning(
                            "Rerank provider marked unhealthy", provider=provider.name
                        )

                logger.warning(
                    "Rerank request failed",
                    provider=provider.name,
                    attempt=attempt + 1,
                    error=str(e)[:200],
                )

        raise last_error  # type: ignore[misc]

    def get_stats(self) -> dict[str, Any]:
        return {
            "service": "rerank",
            "providers": [
                {
                    "name": p.name,
                    "model": p.model,
                    "healthy": p.is_healthy,
                    "request_count": p.request_count,
                    "error_count": p.error_count,
                }
                for p in self._providers
            ],
        }


# =============================================================================
# 全局池管理
# =============================================================================

_llm_pool: LiteLLMPool | None = None
_embedding_pool: LiteLLMPool | None = None
_rerank_pool: RerankPool | None = None


def _parse_litellm_model_list(json_str: str, service_type: str) -> list[dict[str, Any]]:
    """解析 JSON provider 配置为 LiteLLM model_list 格式"""
    if not json_str:
        return []
    try:
        items = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return []

    model_list = []
    for item in items:
        name = item.get("name", "unnamed")
        model = item.get("model", "")
        api_url = item.get("api_url", "")
        api_key = item.get("api_key", "")
        rpm_limit = item.get("rpm_limit", 10)
        priority = item.get("priority", 1)

        # LiteLLM 需要 openai/ 前缀来使用 OpenAI 兼容端点
        litellm_model = model
        if not litellm_model.startswith("openai/"):
            litellm_model = f"openai/{litellm_model}"

        litellm_params = {
            "model": litellm_model,
            "api_key": api_key,
            "rpm": rpm_limit,
            "order": priority,
        }
        # 自定义 base_url（非默认 OpenAI 端点时必须设置）
        if api_url:
            # 去掉末尾的 /chat/completions 或 /v1 等路径，保留 base
            base = api_url.rstrip("/")
            if base.endswith("/v1"):
                base = base[:-3]
            litellm_params["api_base"] = base + "/v1"

        # model_name 使用实际模型名（如 "Qwen3-8B"），同一模型的 provider 组成一个路由组
        # 原始别名（如 "gitee-1"）存入 model_info，供 create_llm 追踪使用
        group_name = model.replace("openai/", "", 1)
        model_list.append(
            {
                "model_name": group_name,
                "litellm_params": litellm_params,
                "model_info": {"provider_alias": name},
            }
        )

    return model_list


def _parse_rerank_providers(json_str: str) -> list[RerankProvider]:
    """解析 JSON provider 配置为 RerankProvider 列表"""
    if not json_str:
        return []
    try:
        items = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return []

    return [
        RerankProvider(
            name=item.get("name", "unnamed"),
            model=item.get("model", ""),
            api_url=item.get("api_url", ""),
            api_key=item.get("api_key", ""),
            rpm_limit=item.get("rpm_limit", 10),
            priority=item.get("priority", 1),
        )
        for item in items
    ]


async def _load_enabled_provider_configs_from_db() -> tuple[
    dict[str, list[dict[str, Any]]], bool
]:
    """Load enabled provider configs from provider_registry.

    Returns (configs_by_kind, registry_has_rows). If the registry has rows, it is
    the runtime source of truth, including the case where every provider is disabled.
    """
    from sqlalchemy import text

    from .crypto import decrypt_key
    from .database import get_database

    db = get_database()
    async with db.session() as session:
        total_result = await session.execute(
            text("SELECT COUNT(*) FROM provider_registry")
        )
        registry_has_rows = bool(total_result.scalar() or 0)
        result = await session.execute(
            text("""
                SELECT kind, display_name, base_url, model, api_key_enc, rpm_limit, priority
                FROM provider_registry
                WHERE is_enabled = true
                ORDER BY kind, priority DESC, created_at ASC
            """)
        )
        rows = result.fetchall()

    configs: dict[str, list[dict[str, Any]]] = {
        "llm": [],
        "embedding": [],
        "rerank": [],
    }
    for row in rows:
        kind = row[0]
        if kind not in configs:
            continue
        api_key = ""
        if row[4]:
            try:
                api_key = decrypt_key(row[4])
            except Exception as e:
                logger.warning(
                    "Skipping provider with undecryptable key",
                    provider=row[1],
                    error=str(e),
                )
                continue
        configs[kind].append(
            {
                "name": row[1],
                "model": row[3] or "",
                "api_url": row[2] or "",
                "api_key": api_key,
                "rpm_limit": row[5] or 10,
                "priority": row[6] or 100,
            }
        )

    return configs, registry_has_rows


def _set_pools_from_configs(configs: dict[str, list[dict[str, Any]]]) -> int:
    """Replace runtime pools from normalized provider configs."""
    global _llm_pool, _embedding_pool, _rerank_pool

    reloaded = 0

    llm_model_list = _parse_litellm_model_list(
        json.dumps(configs.get("llm", [])), "llm"
    )
    _llm_pool = LiteLLMPool("llm", llm_model_list) if llm_model_list else None
    reloaded += len(llm_model_list)

    emb_model_list = _parse_litellm_model_list(
        json.dumps(configs.get("embedding", [])), "embedding"
    )
    _embedding_pool = (
        LiteLLMPool("embedding", emb_model_list) if emb_model_list else None
    )
    reloaded += len(emb_model_list)

    rerank_providers = _parse_rerank_providers(json.dumps(configs.get("rerank", [])))
    _rerank_pool = RerankPool(rerank_providers) if rerank_providers else None
    reloaded += len(rerank_providers)

    return reloaded


async def reload_pools_from_db() -> int:
    """Hot reload runtime pools from enabled provider_registry rows."""
    configs, _ = await _load_enabled_provider_configs_from_db()
    reloaded = _set_pools_from_configs(configs)
    logger.info(
        "Provider pools reloaded from DB",
        reloaded=reloaded,
        llm=len(configs.get("llm", [])),
        embedding=len(configs.get("embedding", [])),
        rerank=len(configs.get("rerank", [])),
    )
    return reloaded


async def init_pools() -> None:
    """Initialize provider pools.

    provider_registry is the runtime source of truth once it has rows. Environment
    variables are only a bootstrap fallback for an empty registry.
    """
    global _llm_pool, _embedding_pool, _rerank_pool

    from ..config import get_settings

    settings = get_settings()

    try:
        db_configs, registry_has_rows = await _load_enabled_provider_configs_from_db()
        if registry_has_rows:
            reloaded = _set_pools_from_configs(db_configs)
            logger.info(
                "Provider pools initialized from DB",
                reloaded=reloaded,
                llm=len(db_configs.get("llm", [])),
                embedding=len(db_configs.get("embedding", [])),
                rerank=len(db_configs.get("rerank", [])),
            )
            return
    except Exception as e:
        logger.warning(
            "Failed to initialize provider pools from DB, falling back to env",
            error=str(e),
        )

    # --- LLM Pool ---
    llm_model_list = _parse_litellm_model_list(
        str(getattr(settings, "llm_providers_json", None) or ""), "llm"
    )
    if not llm_model_list and settings.llm_api_key:
        # 单 provider fallback：从现有 settings 构建
        base_url = settings.llm_base_url or "https://api.openai.com/v1"
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]

        llm_model_list = [
            {
                "model_name": settings.llm_model,
                "litellm_params": {
                    "model": f"openai/{settings.llm_model}",
                    "api_key": settings.llm_api_key,
                    "api_base": base + "/v1",
                    "rpm": 10,
                },
                "model_info": {"provider_alias": settings.llm_provider},
            }
        ]
    if llm_model_list:
        _llm_pool = LiteLLMPool("llm", llm_model_list)

    # --- Embedding Pool ---
    emb_model_list = _parse_litellm_model_list(
        str(getattr(settings, "embedding_providers_json", None) or ""), "embedding"
    )
    if not emb_model_list and settings.embedding_api_key:
        base = settings.embedding_api_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]

        emb_model_list = [
            {
                "model_name": settings.embedding_model,
                "litellm_params": {
                    "model": f"openai/{settings.embedding_model}",
                    "api_key": settings.embedding_api_key,
                    "api_base": base + "/v1",
                    "rpm": 10,
                },
                "model_info": {"provider_alias": settings.embedding_provider},
            }
        ]
    if emb_model_list:
        _embedding_pool = LiteLLMPool("embedding", emb_model_list)

    # --- Rerank Pool（自定义，不走 LiteLLM）---
    rerank_providers = _parse_rerank_providers(
        str(getattr(settings, "rerank_providers_json", None) or "")
    )
    if not rerank_providers and settings.rerank_api_key:
        rerank_providers = [
            RerankProvider(
                name=settings.rerank_provider,
                model=settings.rerank_model,
                api_url=settings.rerank_api_url,
                api_key=settings.rerank_api_key,
                rpm_limit=10,
            )
        ]
    if rerank_providers:
        _rerank_pool = RerankPool(rerank_providers)

    logger.info(
        "Provider pools initialized",
        llm=len(llm_model_list),
        embedding=len(emb_model_list),
        rerank=len(rerank_providers),
    )


async def close_pools() -> None:
    """关闭所有池"""
    global _llm_pool, _embedding_pool, _rerank_pool
    _llm_pool = None
    _embedding_pool = None
    _rerank_pool = None
    logger.info("Provider pools closed")


# =============================================================================
# 便捷访问函数
# =============================================================================


def get_llm_pool() -> LiteLLMPool:
    if _llm_pool is None:
        raise RuntimeError("LLM pool not initialized. Call init_pools() first.")
    return _llm_pool


def get_llm_available_slots(default: int = 10) -> int:
    """Return the current LLM queue capacity derived from enabled providers."""
    if _llm_pool is None:
        return max(1, default)
    return _llm_pool.get_total_rpm_limit(default_per_deployment=default)


def get_embedding_pool() -> LiteLLMPool:
    if _embedding_pool is None:
        raise RuntimeError("Embedding pool not initialized. Call init_pools() first.")
    return _embedding_pool


def get_rerank_pool() -> RerankPool:
    if _rerank_pool is None:
        raise RuntimeError("Rerank pool not initialized. Call init_pools() first.")
    return _rerank_pool
