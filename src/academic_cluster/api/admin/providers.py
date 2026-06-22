"""
管理后台 - Provider 管理

提供 LLM Provider 的 CRUD、健康检查、热重载端点。
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from ...services.crypto import decrypt_key, encrypt_key, mask_key
from ...services.database import DatabaseService, get_database
from ..dependencies import require_admin

logger = structlog.get_logger()

router = APIRouter(tags=["admin-providers"])


async def _reload_runtime_pools() -> int:
    """Best-effort runtime provider pool reload from enabled DB rows."""
    try:
        from ...services.provider_pool import reload_pools_from_db

        return await reload_pools_from_db()
    except Exception as e:
        logger.warning("Failed to reload provider pools", error=str(e))
        return 0


def _pricing_model_candidates(model_name: str | None) -> list[str]:
    """Return model variants commonly seen from OpenAI-compatible providers."""
    if not model_name:
        return []
    raw = str(model_name).strip()
    candidates: list[str] = []
    for value in (raw, raw.removeprefix("openai/")):
        if value and value not in candidates:
            candidates.append(value)
        if "/" in value:
            short = value.rsplit("/", 1)[-1]
            if short and short not in candidates:
                candidates.append(short)
    return candidates


# =============================================================================
# 请求/响应模型
# =============================================================================


class ProviderCreateRequest(BaseModel):
    """创建 Provider 请求"""

    kind: str = Field(..., pattern="^(llm|embedding|rerank)$")
    display_name: str = Field(..., min_length=1, max_length=100)
    base_url: str = Field(..., min_length=1)
    model: str | None = None
    api_key: str | None = None
    is_enabled: bool = True
    priority: int = Field(default=100, ge=1)
    rpm_limit: int = Field(default=10, ge=1)
    weight: int = Field(default=1, ge=1)
    extra_keys: list[str] | None = None
    key_strategy: str = Field(
        default="round_robin", pattern="^(round_robin|random|priority)$"
    )
    auto_ban: bool = True
    test_model: str | None = None
    input_price_per_m: float = Field(default=0, ge=0, description="输入价格 $/M tokens")
    output_price_per_m: float = Field(
        default=0, ge=0, description="输出价格 $/M tokens"
    )
    metadata: dict | None = None


class ProviderUpdateRequest(BaseModel):
    """更新 Provider 请求"""

    display_name: str | None = None
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    is_enabled: bool | None = None
    priority: int | None = None
    rpm_limit: int | None = None
    weight: int | None = None
    extra_keys: list[str] | None = None
    key_strategy: str | None = None
    auto_ban: bool | None = None
    test_model: str | None = None
    input_price_per_m: float | None = None
    output_price_per_m: float | None = None
    metadata: dict | None = None


class ProviderResponse(BaseModel):
    """Provider 响应"""

    id: str
    kind: str
    display_name: str
    base_url: str
    model: str | None = None
    api_key_hint: str | None = None
    is_enabled: bool = True
    priority: int = 100
    rpm_limit: int = 10
    weight: int = 1
    key_strategy: str = "round_robin"
    health_status: str = "unknown"
    last_health_check: str | None = None
    last_error: str | None = None
    failure_count: int = 0
    auto_ban: bool = True
    cooldown_until: str | None = None
    test_model: str | None = None
    input_price_per_m: float = 0
    output_price_per_m: float = 0
    metadata: dict | None = None
    extra_key_count: int = 0
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class ProviderListResponse(BaseModel):
    """Provider 列表响应"""

    providers: list[ProviderResponse]
    total: int


class HealthTestResponse(BaseModel):
    """健康检查响应"""

    provider_id: str
    healthy: bool
    latency_ms: float | None = None
    message: str = ""


class ReloadResult(BaseModel):
    """热重载结果"""

    reloaded: int
    message: str


# =============================================================================
# 辅助函数
# =============================================================================


def _row_to_provider(row, extra_keys_raw=None) -> ProviderResponse:
    """将数据库行转换为 ProviderResponse（支持 tuple 或 RowMapping）"""
    m = row._mapping if hasattr(row, "_mapping") else row

    api_key_hint = None
    if m["api_key_enc"]:
        try:
            plain = decrypt_key(m["api_key_enc"])
            api_key_hint = mask_key(plain)
        except Exception:
            api_key_hint = "****"

    extra_key_count = 0
    raw = extra_keys_raw if extra_keys_raw is not None else m.get("extra_keys")
    if raw:
        import json

        try:
            keys = json.loads(raw) if isinstance(raw, str) else raw
            extra_key_count = len(keys) if isinstance(keys, list) else 0
        except Exception:  # nosec B110
            pass

    return ProviderResponse(
        id=str(m["id"]),
        kind=m["kind"],
        display_name=m["display_name"],
        base_url=m["base_url"],
        model=m["model"],
        api_key_hint=api_key_hint,
        is_enabled=m["is_enabled"],
        priority=m["priority"],
        rpm_limit=m["rpm_limit"],
        weight=m["weight"],
        key_strategy=m["key_strategy"] or "round_robin",
        health_status=m["health_status"] or "unknown",
        last_health_check=str(m["last_health_check"])
        if m["last_health_check"]
        else None,
        last_error=m["last_error"],
        failure_count=m["failure_count"] or 0,
        auto_ban=m["auto_ban"] if m["auto_ban"] is not None else True,
        cooldown_until=str(m["cooldown_until"]) if m["cooldown_until"] else None,
        test_model=m["test_model"],
        input_price_per_m=float(m.get("input_price_per_m") or 0),
        output_price_per_m=float(m.get("output_price_per_m") or 0),
        metadata=m["metadata"] if isinstance(m["metadata"], dict) else None,
        extra_key_count=extra_key_count,
        created_by=str(m["created_by"]) if m["created_by"] else None,
        created_at=str(m["created_at"]) if m["created_at"] else None,
        updated_at=str(m["updated_at"]) if m["updated_at"] else None,
    )


# =============================================================================
# 端点
# =============================================================================


@router.get("", response_model=ProviderListResponse)
async def list_providers(
    kind: str | None = None,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """列出所有 Provider"""
    conditions = []
    params: dict = {}

    if kind:
        conditions.append("kind = :kind")
        params["kind"] = kind

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    async with db.session() as session:
        result = await session.execute(
            text(f"""
                SELECT id, kind, display_name, base_url, model, api_key_enc,
                       is_enabled, priority, rpm_limit, weight, key_strategy,
                       health_status, last_health_check, last_error, failure_count,
                       auto_ban, cooldown_until, test_model, metadata, created_by,
                       created_at, updated_at, extra_keys,
                       input_price_per_m, output_price_per_m
                FROM provider_registry
                {where_clause}
                ORDER BY kind, priority DESC, created_at DESC
            """),  # nosec B608
            params,
        )
        rows = result.fetchall()

    providers = [_row_to_provider(row) for row in rows]
    return ProviderListResponse(providers=providers, total=len(providers))


@router.post("", response_model=ProviderResponse)
async def create_provider(
    body: ProviderCreateRequest,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """创建 Provider"""
    import json

    # 加密 API Key
    api_key_enc = None
    if body.api_key:
        api_key_enc = encrypt_key(body.api_key)

    # 加密额外 Keys
    extra_keys_enc = []
    if body.extra_keys:
        extra_keys_enc = [encrypt_key(k) for k in body.extra_keys]

    async with db.session() as session:
        result = await session.execute(
            text("""
                INSERT INTO provider_registry (
                    kind, display_name, base_url, model, api_key_enc,
                    is_enabled, priority, rpm_limit, weight, extra_keys,
                    key_strategy, auto_ban, test_model,
                    input_price_per_m, output_price_per_m,
                    metadata, created_by
                ) VALUES (
                    :kind, :display_name, :base_url, :model, :api_key_enc,
                    :is_enabled, :priority, :rpm_limit, :weight, :extra_keys,
                    :key_strategy, :auto_ban, :test_model,
                    :input_price_per_m, :output_price_per_m,
                    :metadata, :created_by
                )
                RETURNING id, created_at
            """),
            {
                "kind": body.kind,
                "display_name": body.display_name,
                "base_url": body.base_url,
                "model": body.model,
                "api_key_enc": api_key_enc,
                "is_enabled": body.is_enabled,
                "priority": body.priority,
                "rpm_limit": body.rpm_limit,
                "weight": body.weight,
                "extra_keys": json.dumps(extra_keys_enc),
                "key_strategy": body.key_strategy,
                "auto_ban": body.auto_ban,
                "test_model": body.test_model,
                "input_price_per_m": body.input_price_per_m,
                "output_price_per_m": body.output_price_per_m,
                "metadata": json.dumps(body.metadata or {}),
                "created_by": admin["id"],
            },
        )
        row = result.fetchone()
        provider_id = str(row[0])

    logger.info(
        "Provider created",
        provider_id=provider_id,
        kind=body.kind,
        name=body.display_name,
    )
    await _reload_runtime_pools()

    return ProviderResponse(
        id=provider_id,
        kind=body.kind,
        display_name=body.display_name,
        base_url=body.base_url,
        model=body.model,
        api_key_hint=mask_key(body.api_key) if body.api_key else None,
        is_enabled=body.is_enabled,
        priority=body.priority,
        rpm_limit=body.rpm_limit,
        weight=body.weight,
        key_strategy=body.key_strategy,
        health_status="unknown",
        auto_ban=body.auto_ban,
        test_model=body.test_model,
        metadata=body.metadata,
        extra_key_count=len(body.extra_keys) if body.extra_keys else 0,
        created_at=str(row[1]),
    )


@router.patch("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: str,
    body: ProviderUpdateRequest,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """更新 Provider"""
    import json

    # 构建动态 UPDATE
    updates = []
    params: dict = {"id": provider_id}

    if body.display_name is not None:
        updates.append("display_name = :display_name")
        params["display_name"] = body.display_name
    if body.base_url is not None:
        updates.append("base_url = :base_url")
        params["base_url"] = body.base_url
    if body.model is not None:
        updates.append("model = :model")
        params["model"] = body.model
    if body.api_key is not None:
        updates.append("api_key_enc = :api_key_enc")
        params["api_key_enc"] = encrypt_key(body.api_key)
    if body.is_enabled is not None:
        updates.append("is_enabled = :is_enabled")
        params["is_enabled"] = body.is_enabled
    if body.priority is not None:
        updates.append("priority = :priority")
        params["priority"] = body.priority
    if body.rpm_limit is not None:
        updates.append("rpm_limit = :rpm_limit")
        params["rpm_limit"] = body.rpm_limit
    if body.weight is not None:
        updates.append("weight = :weight")
        params["weight"] = body.weight
    if body.extra_keys is not None:
        updates.append("extra_keys = :extra_keys")
        params["extra_keys"] = json.dumps([encrypt_key(k) for k in body.extra_keys])
    if body.key_strategy is not None:
        updates.append("key_strategy = :key_strategy")
        params["key_strategy"] = body.key_strategy
    if body.auto_ban is not None:
        updates.append("auto_ban = :auto_ban")
        params["auto_ban"] = body.auto_ban
    if body.test_model is not None:
        updates.append("test_model = :test_model")
        params["test_model"] = body.test_model
    if body.metadata is not None:
        updates.append("metadata = :metadata")
        params["metadata"] = json.dumps(body.metadata)
    if body.input_price_per_m is not None:
        updates.append("input_price_per_m = :input_price_per_m")
        params["input_price_per_m"] = body.input_price_per_m
    if body.output_price_per_m is not None:
        updates.append("output_price_per_m = :output_price_per_m")
        params["output_price_per_m"] = body.output_price_per_m

    if not updates:
        raise HTTPException(status_code=400, detail="没有要更新的字段")

    async with db.session() as session:
        result = await session.execute(
            text(f"""
                UPDATE provider_registry SET {", ".join(updates)}
                WHERE id = :id
                RETURNING id, kind, display_name, base_url, model, api_key_enc,
                          is_enabled, priority, rpm_limit, weight, key_strategy,
                          health_status, last_health_check, last_error, failure_count,
                          auto_ban, cooldown_until, test_model, metadata, created_by,
                          created_at, updated_at, extra_keys,
                          input_price_per_m, output_price_per_m
            """),  # nosec B608
            params,
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    logger.info("Provider updated", provider_id=provider_id)
    await _reload_runtime_pools()
    return _row_to_provider(row)


@router.delete("/{provider_id}")
async def delete_provider(
    provider_id: str,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """删除 Provider"""
    async with db.session() as session:
        result = await session.execute(
            text("DELETE FROM provider_registry WHERE id = :id RETURNING id"),
            {"id": provider_id},
        )
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="Provider 不存在")

    logger.info("Provider deleted", provider_id=provider_id)
    await _reload_runtime_pools()
    return {"message": "删除成功"}


@router.post("/{provider_id}/test", response_model=HealthTestResponse)
async def test_provider(
    provider_id: str,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """测试 Provider 健康状态"""
    import time

    async with db.session() as session:
        result = await session.execute(
            text("""
                SELECT id, kind, base_url, model, api_key_enc, test_model
                FROM provider_registry WHERE id = :id
            """),
            {"id": provider_id},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    provider_id_str = str(row[0])
    kind = row[1]
    base_url = row[2]
    model = row[3]
    api_key_enc = row[4]
    test_model = row[5]

    if not api_key_enc:
        await _update_health(db, provider_id_str, "error", "未配置 API Key")
        return HealthTestResponse(
            provider_id=provider_id_str, healthy=False, message="未配置 API Key"
        )

    try:
        api_key = decrypt_key(api_key_enc)
    except Exception as e:
        await _update_health(db, provider_id_str, "error", f"API Key 解密失败: {e}")
        return HealthTestResponse(
            provider_id=provider_id_str, healthy=False, message="API Key 解密失败"
        )

    # 根据 kind 执行不同的健康检查
    start = time.time()
    try:
        if kind == "llm":
            await _test_llm(base_url, api_key, test_model or model)
        elif kind == "embedding":
            await _test_embedding(base_url, api_key, test_model or model)
        elif kind == "rerank":
            await _test_rerank(base_url, api_key, test_model or model)
        else:
            raise ValueError(f"Unknown kind: {kind}")

        latency_ms = (time.time() - start) * 1000
        await _update_health(db, provider_id_str, "healthy", None)
        await _reload_runtime_pools()
        logger.info(
            "Provider health test passed",
            provider_id=provider_id_str,
            latency_ms=round(latency_ms),
        )
        return HealthTestResponse(
            provider_id=provider_id_str,
            healthy=True,
            latency_ms=round(latency_ms, 2),
            message="健康",
        )

    except Exception as e:
        latency_ms = (time.time() - start) * 1000
        error_msg = str(e)[:500]
        await _update_health(db, provider_id_str, "error", error_msg)
        await _reload_runtime_pools()
        logger.warning(
            "Provider health test failed", provider_id=provider_id_str, error=error_msg
        )
        return HealthTestResponse(
            provider_id=provider_id_str,
            healthy=False,
            latency_ms=round(latency_ms, 2),
            message=error_msg,
        )


async def _test_llm(base_url: str, api_key: str, model: str):
    """测试 LLM 端点（发送最小请求）"""
    import httpx

    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    url += "/chat/completions"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 1,
            },
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")


async def _test_embedding(base_url: str, api_key: str, model: str):
    """测试 Embedding 端点"""
    import httpx

    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    url += "/embeddings"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "input": "test"},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")


async def _test_rerank(base_url: str, api_key: str, model: str):
    """测试 Rerank 端点"""
    import httpx

    url = base_url.rstrip("/")
    if not url.endswith("/v1"):
        url += "/v1"
    url += "/rerank"

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "query": "test", "documents": ["hello world"]},
        )
        if resp.status_code >= 400:
            raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")


async def _update_health(
    db: DatabaseService, provider_id: str, status: str, error: str | None
):
    """更新 Provider 健康状态"""
    is_healthy = status == "healthy"
    async with db.session() as session:
        if is_healthy:
            await session.execute(
                text("""
                    UPDATE provider_registry
                    SET health_status = :status,
                        last_health_check = NOW(),
                        last_error = :error,
                        failure_count = 0
                    WHERE id = :id
                """),
                {"id": provider_id, "status": status, "error": error},
            )
        else:
            await session.execute(
                text("""
                    UPDATE provider_registry
                    SET health_status = :status,
                        last_health_check = NOW(),
                        last_error = :error,
                        failure_count = failure_count + 1,
                        is_enabled = CASE
                            WHEN auto_ban AND failure_count + 1 >= 3 THEN false
                            ELSE is_enabled
                        END
                    WHERE id = :id
                """),
                {"id": provider_id, "status": status, "error": error},
            )


# --- 定价查询（供其他模块调用） ---


async def get_provider_pricing(
    db: DatabaseService,
    provider_name: str,
    model_name: str,
) -> tuple[float, float]:
    """查询 provider 的输入/输出定价（$/M tokens）

    按 display_name + model 精确匹配，找不到则按 model 名模糊匹配。
    调用时使用当前定价落库，修改后新调用立即生效。
    """
    candidates = _pricing_model_candidates(model_name)

    async with db.session() as session:
        for candidate in candidates:
            result = await session.execute(
                text("""
                    SELECT input_price_per_m, output_price_per_m
                    FROM provider_registry
                    WHERE display_name = :name AND model = :model AND is_enabled = true
                    LIMIT 1
                """),
                {"name": provider_name, "model": candidate},
            )
            row = result.fetchone()
            if row:
                return (float(row[0] or 0), float(row[1] or 0))

        for candidate in candidates:
            result = await session.execute(
                text("""
                    SELECT input_price_per_m, output_price_per_m
                    FROM provider_registry
                    WHERE model = :model AND is_enabled = true
                    LIMIT 1
                """),
                {"model": candidate},
            )
            row = result.fetchone()
            if row:
                return (float(row[0] or 0), float(row[1] or 0))

        row = None
        for candidate in candidates:
            result = await session.execute(
                text("""
                    SELECT input_price_per_m, output_price_per_m
                    FROM provider_registry
                    WHERE (model LIKE :model_prefix OR :model LIKE model || '%')
                      AND is_enabled = true
                    ORDER BY LENGTH(model) ASC
                    LIMIT 1
                """),
                {"model": candidate, "model_prefix": candidate + "%"},
            )
            row = result.fetchone()
            if row:
                break

    if row:
        return (float(row[0] or 0), float(row[1] or 0))
    return (0.0, 0.0)


@router.post("/reload", response_model=ReloadResult)
async def reload_providers(
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """热重载 Provider 配置。DB 中 enabled provider 是运行时唯一来源。"""
    reloaded = await _reload_runtime_pools()
    return ReloadResult(reloaded=reloaded, message=f"成功重载 {reloaded} 个 Provider")


@router.patch("/{provider_id}/toggle")
async def toggle_provider(
    provider_id: str,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """切换 Provider 启用状态"""
    async with db.session() as session:
        result = await session.execute(
            text("""
                UPDATE provider_registry
                SET is_enabled = NOT is_enabled
                WHERE id = :id
                RETURNING id, is_enabled
            """),
            {"id": provider_id},
        )
        row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Provider 不存在")

    state = "启用" if row[1] else "禁用"
    logger.info("Provider toggled", provider_id=provider_id, enabled=row[1])
    await _reload_runtime_pools()
    return {"id": str(row[0]), "is_enabled": row[1], "message": f"已{state}"}
