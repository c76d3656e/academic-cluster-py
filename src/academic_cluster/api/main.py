"""
FastAPI 主应用
"""

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware

from ..config import get_settings

logger = structlog.get_logger()

_ENVIRONMENT_PROVIDER_SOURCE = "environment"


def _provider_metadata(value: Any) -> dict[str, Any]:
    """Normalize one provider metadata value read from PostgreSQL."""

    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _is_environment_seeded_provider(row: Any) -> bool:
    """Identify current and legacy rows created by the environment seed."""

    metadata = _provider_metadata(row[2])
    return row[1] is None and (
        not metadata or metadata.get("source") == _ENVIRONMENT_PROVIDER_SOURCE
    )


async def _seed_admin(db: Any, settings: Any) -> None:
    """启动时确保存在管理员账户（幂等）"""
    from sqlalchemy import text

    from ..services.auth import get_password_service

    admin_password = settings.admin_password
    if not admin_password:
        logger.info(
            "Admin password not configured (ADMIN_PASSWORD is empty), skipping admin seed"
        )
        return

    password_service = get_password_service()
    admin_email = settings.admin_email

    async with db.session() as session:
        result = await session.execute(
            text("SELECT id, hashed_password FROM users WHERE email = :email"),
            {"email": admin_email},
        )
        row = result.fetchone()

    if row is None:
        # 不存在，创建
        hashed = password_service.hash_password(admin_password)
        user_id = await db.save_user(
            {
                "email": admin_email,
                "hashed_password": hashed,
                "full_name": settings.admin_full_name,
                "role": "admin",
                "is_active": True,
            }
        )
        logger.info("Admin user created", email=admin_email, user_id=user_id)
    else:
        # 存在但密码可能被 .env 更新，验证并同步
        if not password_service.verify_password(admin_password, row[1]):
            hashed = password_service.hash_password(admin_password)
            async with db.session() as session:
                await session.execute(
                    text(
                        "UPDATE users SET hashed_password = :pwd, role = 'admin' WHERE id = :id"
                    ),
                    {"pwd": hashed, "id": row[0]},
                )
            logger.info("Admin password updated from .env", email=admin_email)
        else:
            # 确保角色是 admin
            async with db.session() as session:
                await session.execute(
                    text(
                        "UPDATE users SET role = 'admin' WHERE id = :id AND role != 'admin'"
                    ),
                    {"id": row[0]},
                )


async def _seed_providers(db: Any, settings: Any) -> None:
    """启动时将 .env 中的 Provider 配置同步到 provider_registry 表（幂等）"""
    from sqlalchemy import text

    from ..services.crypto import encrypt_key

    providers_to_seed = []

    # LLM Provider
    if settings.llm_api_key:
        base_url = settings.llm_base_url or "https://api.openai.com/v1"
        providers_to_seed.append(
            {
                "kind": "llm",
                "display_name": settings.llm_provider,
                "base_url": base_url,
                "model": settings.llm_model,
                "api_key": settings.llm_api_key,
                "rpm_limit": 10,
                "priority": 100,
            }
        )

    # Embedding Provider
    if settings.embedding_api_key:
        providers_to_seed.append(
            {
                "kind": "embedding",
                "display_name": settings.embedding_provider,
                "base_url": settings.embedding_api_url,
                "model": settings.embedding_model,
                "api_key": settings.embedding_api_key,
                "rpm_limit": 10,
                "priority": 100,
            }
        )

    # Multi-provider JSON
    for json_str, kind in [
        (getattr(settings, "llm_providers_json", None), "llm"),
        (getattr(settings, "embedding_providers_json", None), "embedding"),
    ]:
        if not json_str:
            continue
        try:
            items = json.loads(json_str)
        except (json.JSONDecodeError, TypeError):
            logger.warning("Ignoring malformed provider seed JSON", kind=kind)
            continue
        if not isinstance(items, list):
            logger.warning("Ignoring non-list provider seed JSON", kind=kind)
            continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                logger.warning(
                    "Ignoring non-object provider seed entry",
                    kind=kind,
                    index=index,
                )
                continue
            name = item.get("name")
            model = item.get("model")
            api_key = item.get("api_key")
            base_url = item.get("api_url", "")
            if not all(
                isinstance(value, str) and value.strip()
                for value in (name, model, api_key)
            ) or not isinstance(base_url, str):
                logger.warning(
                    "Ignoring incomplete provider seed entry",
                    kind=kind,
                    index=index,
                )
                continue
            assert isinstance(name, str)
            assert isinstance(model, str)
            assert isinstance(api_key, str)
            raw_rpm_limit = item.get("rpm_limit", 10)
            raw_priority = item.get("priority", 100)
            if isinstance(raw_rpm_limit, bool) or isinstance(raw_priority, bool):
                logger.warning(
                    "Ignoring provider seed with boolean routing limits",
                    kind=kind,
                    index=index,
                )
                continue
            try:
                rpm_limit = int(raw_rpm_limit)
                priority = int(raw_priority)
            except (TypeError, ValueError, OverflowError):
                logger.warning(
                    "Ignoring provider seed with invalid routing limits",
                    kind=kind,
                    index=index,
                )
                continue
            if rpm_limit < 1 or priority < 1:
                logger.warning(
                    "Ignoring provider seed with non-positive routing limits",
                    kind=kind,
                    index=index,
                )
                continue
            providers_to_seed.append(
                {
                    "kind": kind,
                    "display_name": name.strip(),
                    "base_url": base_url.strip(),
                    "model": model.strip(),
                    "api_key": api_key.strip(),
                    "rpm_limit": rpm_limit,
                    "priority": priority,
                }
            )

    if not providers_to_seed:
        return

    async with db.session() as session:
        for p in providers_to_seed:
            # Environment seeds have no creator.  Rows created through the admin API
            # keep ownership of their key even if they happen to reuse the same name.
            result = await session.execute(
                text("""
                    SELECT id, created_by, metadata
                    FROM provider_registry
                    WHERE kind = :kind AND display_name = :name
                    ORDER BY created_at ASC, id ASC
                """),
                {"kind": p["kind"], "name": p["display_name"]},
            )
            existing_rows = result.fetchall()
            api_key_enc = encrypt_key(p["api_key"]) if p["api_key"] else None
            seed_metadata = json.dumps(
                {"source": _ENVIRONMENT_PROVIDER_SOURCE}, ensure_ascii=False
            )
            environment_row = next(
                (row for row in existing_rows if _is_environment_seeded_provider(row)),
                None,
            )
            if environment_row is not None:
                await session.execute(
                    text("""
                        UPDATE provider_registry
                        SET base_url = COALESCE(NULLIF(:base_url, ''), base_url),
                            model = COALESCE(NULLIF(:model, ''), model),
                            api_key_enc = COALESCE(:api_key_enc, api_key_enc),
                            rpm_limit = :rpm_limit,
                            priority = :priority,
                            metadata = COALESCE(metadata, '{}'::jsonb)
                                || CAST(:metadata AS jsonb),
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = :id
                    """),
                    {
                        "id": environment_row[0],
                        "base_url": p["base_url"],
                        "model": p["model"],
                        "api_key_enc": api_key_enc,
                        "rpm_limit": p["rpm_limit"],
                        "priority": p["priority"],
                        "metadata": seed_metadata,
                    },
                )
                logger.info(
                    "Updated provider from env",
                    kind=p["kind"],
                    name=p["display_name"],
                    key_rotated=api_key_enc is not None,
                )
                continue
            if existing_rows:
                logger.info(
                    "Skipped env provider seed because an admin-owned row uses the name",
                    kind=p["kind"],
                    name=p["display_name"],
                )
                continue

            await session.execute(
                text("""
                    INSERT INTO provider_registry (
                        kind, display_name, base_url, model, api_key_enc,
                        rpm_limit, priority, health_status, metadata
                    )
                    VALUES (
                        :kind, :name, :base_url, :model, :api_key_enc,
                        :rpm_limit, :priority, 'unknown', CAST(:metadata AS jsonb)
                    )
                """),
                {
                    "kind": p["kind"],
                    "name": p["display_name"],
                    "base_url": p["base_url"],
                    "model": p["model"],
                    "api_key_enc": api_key_enc,
                    "rpm_limit": p["rpm_limit"],
                    "priority": p["priority"],
                    "metadata": seed_metadata,
                },
            )
            logger.info(
                "Seeded provider from env", kind=p["kind"], name=p["display_name"]
            )


async def _ensure_evidence_card_schema(db: Any) -> None:
    """Add project-scoped evidence-card persistence for existing databases."""
    from sqlalchemy import text

    async with db.session() as session:
        await session.execute(
            text("ALTER TABLE evidence_cards ADD COLUMN IF NOT EXISTS project_id UUID")
        )
        await session.execute(
            text("""
            UPDATE evidence_cards ec
            SET project_id = c.project_id
            FROM clusters c
            WHERE ec.cluster_id = c.id
              AND ec.project_id IS NULL
              AND EXISTS (
                  SELECT 1 FROM projects p WHERE p.id = c.project_id
              )
        """)
        )
        await session.execute(
            text("""
            WITH ranked_cards AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY project_id, paper_id
                           ORDER BY created_at ASC, id ASC
                       ) AS rn
                FROM evidence_cards
                WHERE project_id IS NOT NULL
            )
            DELETE FROM evidence_cards ec
            USING ranked_cards rc
            WHERE ec.id = rc.id AND rc.rn > 1
        """)
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_evidence_cards_project_id ON evidence_cards(project_id)"
            )
        )
        await session.execute(
            text("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_cards_project_paper
            ON evidence_cards(project_id, paper_id)
            WHERE project_id IS NOT NULL
        """)
        )


async def _ensure_observability_schema(db: Any) -> None:
    """Add request-level usage/audit fields for existing databases."""
    from sqlalchemy import text

    async with db.session() as session:
        for column_sql in [
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS project_id UUID",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS node_name VARCHAR(100)",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS requested_model VARCHAR(200)",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS upstream_model VARCHAR(200)",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS api_base_url VARCHAR(500)",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS api_key_hint VARCHAR(20)",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS error_message TEXT",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS http_status_code INTEGER",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS is_stream BOOLEAN DEFAULT FALSE",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS first_token_ms BIGINT",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS input_preview TEXT",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS output_preview TEXT",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS request_metadata JSONB",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS retry_of UUID",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS input_price_per_m DOUBLE PRECISION",
            "ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS output_price_per_m DOUBLE PRECISION",
        ]:
            await session.execute(text(column_sql))

        await session.execute(
            text("""
            UPDATE llm_calls lc
            SET project_id = pr.project_id
            FROM pipeline_runs pr
            WHERE lc.pipeline_run_id = pr.id
              AND lc.project_id IS NULL
        """)
        )
        await session.execute(
            text("""
            UPDATE llm_calls lc
            SET node_name = ne.node_name
            FROM node_executions ne
            WHERE lc.node_execution_id = ne.id
              AND lc.node_name IS NULL
        """)
        )
        await session.execute(
            text("""
            UPDATE llm_calls
            SET requested_model = COALESCE(requested_model, model_name),
                upstream_model = COALESCE(upstream_model, model_name)
            WHERE requested_model IS NULL OR upstream_model IS NULL
        """)
        )
        await session.execute(
            text("ALTER TABLE llm_calls ALTER COLUMN status SET DEFAULT 'running'")
        )

        for index_sql in [
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_project ON llm_calls(project_id)",
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_node_name ON llm_calls(node_name)",
            "CREATE INDEX IF NOT EXISTS idx_llm_calls_requested_model ON llm_calls(requested_model)",
        ]:
            await session.execute(text(index_sql))


async def _ensure_embedding_schema(db: Any) -> None:
    """Make stored embeddings dimension-flexible and safe for exact KNN queries.

    A dimension-flexible pgvector column accepts up to 16,000 dimensions. HNSW
    cannot index such a column without fixing one dimension, which would break
    administrator-controlled model changes. The runtime therefore uses exact
    similarity queries and a B-tree lookup index for model/dimension filtering.
    """

    from sqlalchemy import text

    async with db.session() as session:
        await session.execute(
            text(
                "ALTER TABLE embeddings ALTER COLUMN vector TYPE vector "
                "USING vector::vector"
            )
        )
        await session.execute(
            text("ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS dimensions INTEGER")
        )
        await session.execute(
            text(
                "UPDATE embeddings SET dimensions = vector_dims(vector) "
                "WHERE dimensions IS NULL AND vector IS NOT NULL"
            )
        )
        await session.execute(
            text(
                "ALTER TABLE embeddings ALTER COLUMN dimensions DROP DEFAULT"
            )
        )
        await session.execute(
            text(
                """
                DROP INDEX IF EXISTS idx_embeddings_vector;
                """
            )
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_embeddings_lookup "
                "ON embeddings (model_name, dimensions, paper_id)"
            )
        )
        await session.execute(
            text("""
                CREATE OR REPLACE FUNCTION search_similar_papers(
                    query_embedding vector,
                    match_count INTEGER DEFAULT 10,
                    match_threshold DOUBLE PRECISION DEFAULT 0.5
                ) RETURNS TABLE (paper_id UUID, similarity DOUBLE PRECISION)
                LANGUAGE sql STABLE AS $$
                    SELECT e.paper_id,
                           1 - (e.vector <=> query_embedding) AS similarity
                    FROM embeddings e
                    WHERE vector_dims(e.vector) = vector_dims(query_embedding)
                      AND 1 - (e.vector <=> query_embedding) > match_threshold
                    ORDER BY e.vector <=> query_embedding
                    LIMIT match_count
                $$
            """)
        )


async def _ensure_source_registry_schema(db: Any) -> None:
    """Create source_registry for existing databases."""
    from ..services.source_config import ensure_source_registry_schema

    await ensure_source_registry_schema(db)


async def _shutdown_application_services() -> None:
    """Close shared services in dependency order."""

    from ..agents.checkpoint import close_checkpointer
    from ..services import close_cache, close_database, close_vector_store
    from ..services.agent_runtime import close_agent_run_manager
    from ..services.langfuse_observability import ashutdown_langfuse_observability
    from ..services.provider_pool import close_pools

    closers = (
        ("Agent runtime", close_agent_run_manager),
        ("Langfuse observability", ashutdown_langfuse_observability),
        ("provider pools", close_pools),
        ("Agent checkpointer", close_checkpointer),
        ("database", close_database),
        ("cache", close_cache),
        ("vector store", close_vector_store),
    )
    failures: list[tuple[str, Exception]] = []
    for name, close in closers:
        try:
            await close()
        except Exception as error:
            failures.append((name, error))
            logger.exception("Service shutdown failed", service=name, error=str(error))
    if failures:
        names = ", ".join(name for name, _error in failures)
        raise RuntimeError(
            f"Failed to close application services: {names}"
        ) from failures[0][1]


async def _cleanup_stale_executions(db: Any) -> None:
    """Reconcile legacy Pipeline and Agent lifecycles independently."""

    try:
        from sqlalchemy import text

        async with db.session() as session:
            result = await session.execute(
                text(
                    "UPDATE projects SET status = 'interrupted' "
                    "WHERE status LIKE 'running%' RETURNING id"
                )
            )
            stale = result.fetchall()
            if stale:
                project_ids = [str(row[0]) for row in stale]
                logger.info(
                    "Marked stale running projects as interrupted",
                    count=len(project_ids),
                    project_ids=project_ids,
                )
                await session.execute(
                    text(
                        "UPDATE pipeline_runs SET status = 'interrupted' "
                        "WHERE project_id = ANY(CAST(:project_ids AS uuid[])) "
                        "AND status = 'running'"
                    ),
                    {"project_ids": project_ids},
                )
    except Exception as error:
        logger.warning("Failed to clean up stale Pipeline runs", error=str(error))

    try:
        affected_agents = await db.cleanup_stale_agent_executions()
        if affected_agents > 0:
            logger.info(
                "Marked stale agent_executions as interrupted",
                count=affected_agents,
            )
    except Exception as error:
        logger.warning("Failed to clean up stale Agent runs", error=str(error))


async def _initialize_application_services(settings: Any) -> None:
    """Initialize every shared service required before the ASGI app can serve."""

    # 初始化服务
    from ..services import get_cache, get_database, get_vector_store

    db = get_database()
    get_cache()
    get_vector_store()

    # A persistent checkpointer is a startup requirement: resume must never
    # silently degrade to process-local memory.
    from ..agents.checkpoint import initialize_checkpointer

    await initialize_checkpointer(settings)

    # 初始化默认管理员账户
    try:
        await _seed_admin(db, settings)
    except Exception as e:
        logger.warning("Failed to seed admin user", error=str(e))

    try:
        await _ensure_observability_schema(db)
        await _ensure_embedding_schema(db)
        await _ensure_evidence_card_schema(db)
        await _ensure_source_registry_schema(db)
        await _seed_providers(db, settings)
    except Exception as e:
        if settings.is_production:
            raise RuntimeError(
                "Failed to initialize production schemas or providers"
            ) from e
        logger.warning(
            "Failed to initialize runtime schemas or seed providers", error=str(e)
        )

    # 初始化 Provider Pool（DB 优先，环境变量仅作空库回退）
    try:
        from ..services.provider_pool import init_pools

        await init_pools()
    except Exception as e:
        if settings.is_production:
            raise RuntimeError("Required production provider pools failed") from e
        logger.warning("Failed to init provider pools", error=str(e))

    # 初始化 Pipeline 配置表
    try:
        from .admin.pipeline_config import _ensure_defaults, init_pipeline_config_table

        await init_pipeline_config_table()
        await _ensure_defaults()
    except Exception as e:
        logger.warning("Failed to init pipeline config table", error=str(e))

    await _cleanup_stale_executions(db)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期管理"""
    settings = get_settings()

    from ..services.observability import setup_structlog

    setup_structlog(settings.log_level)

    logger.info("Starting application")

    # 安全校验: 生产环境检查配置是否安全
    settings.validate_security()

    active_error: BaseException | None = None
    try:
        await _initialize_application_services(settings)
        yield
    except BaseException as error:
        active_error = error
        raise
    finally:
        # 清理资源，即使 ASGI 服务因异常退出也必须先 drain Agent。
        logger.info("Shutting down application")
        try:
            await _shutdown_application_services()
        except Exception as cleanup_error:
            if active_error is None:
                raise
            logger.exception(
                "Service shutdown also failed while handling an application error",
                error=str(cleanup_error),
            )


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    settings = get_settings()

    app = FastAPI(
        title="Academic Cluster",
        description="学术论文聚类与综述生成系统",
        version="0.1.0",
        lifespan=lifespan,
    )

    from .security_middleware import RequestSecurityMiddleware

    app.add_middleware(RequestSecurityMiddleware, settings=settings)

    # CORS 配置
    # 安全修复: 生产环境不允许 allow_origins=["*"] + allow_credentials=True 的组合
    # 该组合允许任意来源携带凭据发起跨域请求，存在 CSRF 风险
    if settings.cors_origins:
        cors_origins = settings.cors_origin_list
    elif settings.app_debug:
        cors_origins = ["*"]
    else:
        cors_origins = ["http://localhost:3000", "http://localhost:5173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials="*" not in cors_origins,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # 注册路由
    from .admin import router as admin_router
    from .agent_routes import router as agent_router
    from .auth_routes import router as auth_router
    from .console import router as console_router
    from .routes import router
    from .sse import router as sse_router

    app.include_router(auth_router, prefix="/api")
    app.include_router(router, prefix="/api")
    app.include_router(agent_router, prefix="/api")
    app.include_router(sse_router, prefix="/api")
    app.include_router(console_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")

    @app.get("/health")
    async def health(response: Response) -> dict[str, Any]:
        issues: list[str] = []
        from ..agents.checkpoint import check_runtime_lock_health
        from ..services.provider_pool import require_agent_provider_pools

        if not await check_runtime_lock_health():
            issues.append("checkpoint")
        try:
            require_agent_provider_pools()
        except RuntimeError as error:
            issues.append(str(error))
        if issues:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return {"status": "unhealthy", "issues": issues}
        return {"status": "healthy", "issues": []}

    return app


app = create_app()
