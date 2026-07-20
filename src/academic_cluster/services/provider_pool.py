"""
Provider Pool - 基于 LiteLLM Router 的多端点负载均衡

LLM / Embedding 使用 LiteLLM Router；rerank 使用同一 Registry 的 HTTP 路由配置。
"""

import json
from typing import Any

import structlog

logger = structlog.get_logger()


def _toml_default_rpm() -> int:
    from .runtime_policy import config_definitions

    return int(config_definitions()["provider.default_rpm"]["value"])


def _normalize_openai_model(model: str) -> tuple[str, str]:
    """Return the Router group name and exactly-once OpenAI provider model."""

    group_name = model.strip()
    while group_name.startswith("openai/"):
        group_name = group_name.removeprefix("openai/")
    if not group_name:
        raise ValueError("provider model name is empty after normalization")
    return group_name, f"openai/{group_name}"


def _normalize_openai_api_base(api_url: str) -> str:
    """Normalize an OpenAI-compatible base URL supplied as a base or endpoint."""

    base = api_url.strip().rstrip("/")
    for suffix in ("/chat/completions", "/embeddings"):
        if base.casefold().endswith(suffix):
            base = base[: -len(suffix)].rstrip("/")
            break
    if not base.casefold().endswith("/v1"):
        base += "/v1"
    return base


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
        self,
        service_name: str,
        model_list: list[dict[str, Any]],
        *,
        routing_policy: Any | None = None,
        **router_kwargs: Any,
    ) -> None:
        self.service_name = service_name
        self._model_list = model_list
        self._router_kwargs = router_kwargs
        self.routing_policy = routing_policy
        self._router: Any = None

    def _ensure_router(self) -> None:
        """延迟初始化 Router（避免导入时就需要 litellm）"""
        if self._router is not None:
            return

        from litellm import Router  # type: ignore[attr-defined]

        if self.routing_policy is None:
            from .runtime_policy import config_definitions

            definitions = config_definitions()

            def policy_value(key: str) -> str:
                return str(definitions[key]["value"])

            router_retries = int(policy_value("provider.router_retries"))
            request_timeout = float(policy_value("provider.request_timeout_seconds"))
            retry_after = float(policy_value("provider.retry_delay_seconds"))
            allowed_failures = int(policy_value("provider.allowed_failures"))
            cooldown_seconds = float(policy_value("provider.cooldown_seconds"))
        else:
            router_retries = self.routing_policy.provider_router_retries
            request_timeout = self.routing_policy.provider_request_timeout_seconds
            retry_after = self.routing_policy.provider_retry_delay_seconds
            allowed_failures = self.routing_policy.provider_allowed_failures
            cooldown_seconds = self.routing_policy.provider_cooldown_seconds

        self._router = Router(
            model_list=self._model_list,
            routing_strategy="simple-shuffle",
            # The audited client owns the request-level retry budget. Keep a
            # single Router retry for provider failover without multiplying a
            # transient outage into nested retry storms.
            num_retries=router_retries,
            timeout=request_timeout,
            retry_after=max(0, int(retry_after)),
            enable_pre_call_checks=True,
            allowed_fails=allowed_failures,
            cooldown_time=cooldown_seconds,
            disable_cooldowns=False,
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

    def get_model_name(self) -> str:
        """获取模型别名"""
        if not self._model_list:
            raise RuntimeError(f"No deployments in {self.service_name} pool")
        return str(self._model_list[0]["model_name"])

    @property
    def deployments(self) -> list[dict[str, Any]]:
        """获取所有部署配置"""
        return self._model_list

    def get_total_rpm_limit(self, default_per_deployment: int | None = None) -> int:
        """Return the summed configured RPM budget for this pool."""
        default_per_deployment = (
            _toml_default_rpm()
            if default_per_deployment is None
            else default_per_deployment
        )
        total = 0
        for deployment in self._model_list:
            params = deployment.get("litellm_params", {})
            try:
                rpm = int(params.get("rpm") or default_per_deployment)
            except (TypeError, ValueError):
                rpm = default_per_deployment
            total += max(1, rpm)
        return max(1, total)


# =============================================================================
# 全局池管理
# =============================================================================

_llm_pool: LiteLLMPool | None = None
_embedding_pool: LiteLLMPool | None = None
_rerank_providers: list[dict[str, Any]] = []


def _parse_litellm_model_list(json_str: str, service_type: str) -> list[dict[str, Any]]:
    """解析 JSON provider 配置为 LiteLLM model_list 格式"""
    if not json_str:
        return []
    try:
        items = json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(items, list):
        logger.warning(
            "Ignoring invalid provider JSON: expected a list",
            service=service_type,
        )
        return []

    model_list: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            logger.warning(
                "Skipping invalid provider entry: expected an object",
                service=service_type,
                index=index,
            )
            continue

        model_value = item.get("model")
        api_key_value = item.get("api_key")
        if (
            not isinstance(model_value, str)
            or not model_value.strip()
            or not isinstance(api_key_value, str)
            or not api_key_value.strip()
        ):
            logger.warning(
                "Skipping provider entry without a model or API key",
                service=service_type,
                index=index,
            )
            continue

        api_url_value = item.get("api_url", "")
        if not isinstance(api_url_value, str):
            logger.warning(
                "Skipping provider entry with an invalid API URL",
                service=service_type,
                index=index,
            )
            continue

        raw_rpm_limit = item.get("rpm_limit", _toml_default_rpm())
        raw_priority = item.get("priority", 100)
        if isinstance(raw_rpm_limit, bool) or isinstance(raw_priority, bool):
            logger.warning(
                "Skipping provider entry with boolean routing limits",
                service=service_type,
                index=index,
            )
            continue
        try:
            rpm_limit = int(raw_rpm_limit)
            priority = int(raw_priority)
        except (TypeError, ValueError, OverflowError):
            logger.warning(
                "Skipping provider entry with invalid routing limits",
                service=service_type,
                index=index,
            )
            continue
        if rpm_limit < 1 or priority < 1:
            logger.warning(
                "Skipping provider entry with non-positive routing limits",
                service=service_type,
                index=index,
            )
            continue

        name_value = item.get("name", "unnamed")
        name = (
            name_value.strip()
            if isinstance(name_value, str) and name_value.strip()
            else "unnamed"
        )
        model = model_value.strip()
        api_url = api_url_value.strip()
        api_key = api_key_value.strip()

        # LiteLLM 需要 openai/ 前缀来使用 OpenAI 兼容端点
        try:
            group_name, litellm_model = _normalize_openai_model(model)
        except ValueError:
            logger.warning(
                "Skipping provider entry with an invalid normalized model",
                service=service_type,
                index=index,
            )
            continue

        litellm_params = {
            "model": litellm_model,
            "api_key": api_key,
            "rpm": rpm_limit,
            # provider_registry treats larger priority values as more important,
            # while LiteLLM selects the deployment with the smallest order first.
            "order": -priority,
        }
        # 自定义 base_url（非默认 OpenAI 端点时必须设置）
        if api_url:
            litellm_params["api_base"] = _normalize_openai_api_base(api_url)

        # model_name 使用实际模型名（如 "Qwen3-8B"），同一模型的 provider 组成一个路由组
        # 原始别名（如 "gitee-1"）存入 model_info，供 create_llm 追踪使用
        model_list.append(
            {
                "model_name": group_name,
                "litellm_params": litellm_params,
                "model_info": {"provider_alias": name},
            }
        )

    return model_list


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
            text("""
                SELECT COUNT(*)
                FROM provider_registry
                WHERE kind IN ('llm', 'embedding', 'rerank')
            """)
        )
        registry_has_rows = bool(total_result.scalar() or 0)
        result = await session.execute(
            text("""
                SELECT kind, display_name, base_url, model, api_key_enc,
                       rpm_limit, priority, metadata
                FROM provider_registry
                WHERE kind IN ('llm', 'embedding', 'rerank')
                  AND is_enabled = true
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
                "rpm_limit": row[5] or _toml_default_rpm(),
                "priority": row[6] or 100,
                "metadata": row[7] if len(row) > 7 and isinstance(row[7], dict) else {},
            }
        )

    return configs, registry_has_rows


def _set_pools_from_configs(
    configs: dict[str, list[dict[str, Any]]],
    routing_policy: Any | None = None,
) -> int:
    """Replace runtime pools from normalized provider configs."""
    global _llm_pool, _embedding_pool, _rerank_providers

    reloaded = 0

    llm_model_list = _parse_litellm_model_list(
        json.dumps(configs.get("llm", [])), "llm"
    )
    _llm_pool = (
        LiteLLMPool("llm", llm_model_list, routing_policy=routing_policy)
        if llm_model_list
        else None
    )
    reloaded += len(llm_model_list)

    emb_model_list = _parse_litellm_model_list(
        json.dumps(configs.get("embedding", [])), "embedding"
    )
    _embedding_pool = (
        LiteLLMPool("embedding", emb_model_list, routing_policy=routing_policy)
        if emb_model_list
        else None
    )
    reloaded += len(emb_model_list)

    _rerank_providers = list(configs.get("rerank", []))
    reloaded += len(_rerank_providers)

    return reloaded


def require_agent_provider_pools() -> None:
    """Fail when either provider class required by the Agent is unavailable."""

    missing: list[str] = []
    if _llm_pool is None or not _llm_pool.deployments:
        missing.append("llm")
    if _embedding_pool is None or not _embedding_pool.deployments:
        missing.append("embedding")
    if missing:
        raise RuntimeError(
            "Required Agent provider pools are unavailable: " + ", ".join(missing)
        )


async def reload_pools_from_db() -> int:
    """Hot reload runtime pools from enabled provider_registry rows."""
    configs, _ = await _load_enabled_provider_configs_from_db()
    from .runtime_policy import get_runtime_policy

    reloaded = _set_pools_from_configs(configs, await get_runtime_policy())
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
    global _llm_pool, _embedding_pool, _rerank_providers

    from ..config import get_settings

    # Re-initialization must not let a previous, now-invalid deployment satisfy
    # production readiness when the current source contains no usable provider.
    _llm_pool = None
    _embedding_pool = None
    _rerank_providers = []
    settings = get_settings()

    try:
        db_configs, registry_has_rows = await _load_enabled_provider_configs_from_db()
    except Exception as e:
        logger.warning(
            "Failed to initialize provider pools from DB, falling back to env",
            error=str(e),
        )
    else:
        if registry_has_rows:
            from .runtime_policy import get_runtime_policy

            reloaded = _set_pools_from_configs(
                db_configs,
                await get_runtime_policy(),
            )
            logger.info(
                "Provider pools initialized from DB",
                reloaded=reloaded,
                llm=len(db_configs.get("llm", [])),
                embedding=len(db_configs.get("embedding", [])),
                rerank=len(db_configs.get("rerank", [])),
            )
            if settings.is_production:
                require_agent_provider_pools()
            return

    # --- LLM Pool ---
    llm_model_list = _parse_litellm_model_list(
        str(getattr(settings, "llm_providers_json", None) or ""), "llm"
    )
    if not llm_model_list and settings.llm_api_key:
        # 单 provider fallback：从现有 settings 构建
        base_url = settings.llm_base_url or "https://api.openai.com/v1"
        group_name, litellm_model = _normalize_openai_model(settings.llm_model)

        llm_model_list = [
            {
                "model_name": group_name,
                "litellm_params": {
                    "model": litellm_model,
                    "api_key": settings.llm_api_key,
                    "api_base": _normalize_openai_api_base(base_url),
                "rpm": _toml_default_rpm(),
                },
                "model_info": {"provider_alias": settings.llm_provider},
            }
        ]
    if llm_model_list:
        from .runtime_policy import get_runtime_policy

        _llm_pool = LiteLLMPool(
            "llm", llm_model_list, routing_policy=await get_runtime_policy()
        )

    # --- Embedding Pool ---
    emb_model_list = _parse_litellm_model_list(
        str(getattr(settings, "embedding_providers_json", None) or ""), "embedding"
    )
    if not emb_model_list and settings.embedding_api_key:
        group_name, litellm_model = _normalize_openai_model(settings.embedding_model)

        emb_model_list = [
            {
                "model_name": group_name,
                "litellm_params": {
                    "model": litellm_model,
                    "api_key": settings.embedding_api_key,
                    "api_base": _normalize_openai_api_base(settings.embedding_api_url),
                    "rpm": _toml_default_rpm(),
                },
                "model_info": {"provider_alias": settings.embedding_provider},
            }
        ]
    if emb_model_list:
        from .runtime_policy import get_runtime_policy

        _embedding_pool = LiteLLMPool(
            "embedding", emb_model_list, routing_policy=await get_runtime_policy()
        )

    logger.info(
        "Provider pools initialized",
        llm=len(llm_model_list),
        embedding=len(emb_model_list),
        rerank=len(_rerank_providers),
    )
    if settings.is_production:
        require_agent_provider_pools()


async def close_pools() -> None:
    """关闭所有池"""
    global _llm_pool, _embedding_pool, _rerank_providers
    _llm_pool = None
    _embedding_pool = None
    _rerank_providers = []
    logger.info("Provider pools closed")


# =============================================================================
# 便捷访问函数
# =============================================================================


def get_llm_pool() -> LiteLLMPool:
    if _llm_pool is None:
        raise RuntimeError("LLM pool not initialized. Call init_pools() first.")
    return _llm_pool


def get_llm_available_slots(default: int | None = None) -> int:
    """Return the current LLM queue capacity derived from enabled providers."""
    if _llm_pool is None:
        return max(1, default if default is not None else _toml_default_rpm())
    return _llm_pool.get_total_rpm_limit(default_per_deployment=default)


def get_embedding_pool() -> LiteLLMPool:
    if _embedding_pool is None:
        raise RuntimeError("Embedding pool not initialized. Call init_pools() first.")
    return _embedding_pool


def get_rerank_providers() -> list[dict[str, Any]]:
    """Return enabled rerank providers in configured priority order."""

    return [dict(provider) for provider in _rerank_providers]
