"""
FastAPI 主应用
"""

from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import get_settings

logger = structlog.get_logger()


async def _seed_admin(db, settings):
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


async def _seed_providers(db, settings):
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
            }
        )

    # Rerank Provider
    if settings.rerank_api_key:
        providers_to_seed.append(
            {
                "kind": "rerank",
                "display_name": settings.rerank_provider,
                "base_url": settings.rerank_api_url,
                "model": settings.rerank_model,
                "api_key": settings.rerank_api_key,
            }
        )

    # Multi-provider JSON
    import json

    for json_str, kind in [
        (getattr(settings, "llm_providers_json", None), "llm"),
        (getattr(settings, "embedding_providers_json", None), "embedding"),
        (getattr(settings, "rerank_providers_json", None), "rerank"),
    ]:
        if not json_str:
            continue
        try:
            items = json.loads(json_str)
            for item in items:
                providers_to_seed.append(
                    {
                        "kind": kind,
                        "display_name": item.get("name", "unnamed"),
                        "base_url": item.get("api_url", ""),
                        "model": item.get("model", ""),
                        "api_key": item.get("api_key", ""),
                    }
                )
        except (json.JSONDecodeError, TypeError):
            pass

    if not providers_to_seed:
        return

    async with db.session() as session:
        for p in providers_to_seed:
            # 检查是否已存在同名同 kind 的 provider
            result = await session.execute(
                text(
                    "SELECT id FROM provider_registry WHERE kind = :kind AND display_name = :name"
                ),
                {"kind": p["kind"], "name": p["display_name"]},
            )
            if result.fetchone():
                continue  # 已存在，跳过

            api_key_enc = encrypt_key(p["api_key"]) if p["api_key"] else None
            await session.execute(
                text("""
                    INSERT INTO provider_registry (kind, display_name, base_url, model, api_key_enc, health_status)
                    VALUES (:kind, :name, :base_url, :model, :api_key_enc, 'unknown')
                """),
                {
                    "kind": p["kind"],
                    "name": p["display_name"],
                    "base_url": p["base_url"],
                    "model": p["model"],
                    "api_key_enc": api_key_enc,
                },
            )
            logger.info(
                "Seeded provider from env", kind=p["kind"], name=p["display_name"]
            )


async def _ensure_community_memory_schema(db):
    """Create community memory persistence for existing databases."""
    from sqlalchemy import text

    async with db.session() as session:
        await session.execute(
            text("""
            CREATE TABLE IF NOT EXISTS community_memories (
                id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
                project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
                cluster_id UUID REFERENCES clusters(id) ON DELETE CASCADE,
                summary TEXT,
                method_families JSONB NOT NULL DEFAULT '[]'::jsonb,
                key_claims JSONB NOT NULL DEFAULT '[]'::jsonb,
                limitations JSONB NOT NULL DEFAULT '[]'::jsonb,
                future_directions JSONB NOT NULL DEFAULT '[]'::jsonb,
                foundation_papers JSONB NOT NULL DEFAULT '[]'::jsonb,
                development_papers JSONB NOT NULL DEFAULT '[]'::jsonb,
                frontier_papers JSONB NOT NULL DEFAULT '[]'::jsonb,
                representative_papers JSONB NOT NULL DEFAULT '[]'::jsonb,
                cross_community_links JSONB NOT NULL DEFAULT '[]'::jsonb,
                proof_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, cluster_id)
            )
        """)
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_community_memories_project_id ON community_memories(project_id)"
            )
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_community_memories_cluster_id ON community_memories(cluster_id)"
            )
        )


async def _ensure_evidence_card_schema(db):
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


async def _ensure_observability_schema(db):
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


async def _ensure_source_registry_schema(db):
    """Create source_registry for existing databases."""
    from ..services.source_config import ensure_source_registry_schema

    await ensure_source_registry_schema(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    settings = get_settings()

    from ..services.observability import setup_structlog

    setup_structlog(settings.log_level)

    logger.info("Starting application")

    # 安全校验: 生产环境检查配置是否安全
    settings.validate_security()

    # 初始化服务
    from ..services import get_cache, get_database, get_vector_store

    db = get_database()
    get_cache()
    get_vector_store()

    # 初始化 LangGraph checkpointer（AsyncPostgresSaver）
    try:
        from ..graphs.graph import get_checkpointer

        await get_checkpointer()
    except Exception as e:
        logger.warning(
            "Failed to init AsyncPostgresSaver, will use MemorySaver fallback",
            error=str(e),
        )

    # 初始化默认管理员账户
    try:
        await _seed_admin(db, settings)
    except Exception as e:
        logger.warning("Failed to seed admin user", error=str(e))

    try:
        await _ensure_observability_schema(db)
        await _ensure_evidence_card_schema(db)
        await _ensure_community_memory_schema(db)
        await _ensure_source_registry_schema(db)
        await _seed_providers(db, settings)
    except Exception as e:
        logger.warning(
            "Failed to initialize runtime schemas or seed providers", error=str(e)
        )

    # 初始化 Provider Pool（DB 优先，环境变量仅作空库回退）
    try:
        from ..services.provider_pool import init_pools

        await init_pools()
    except Exception as e:
        logger.warning("Failed to init provider pools", error=str(e))

    # 初始化 Pipeline 配置表
    try:
        from .admin.pipeline_config import _ensure_defaults, init_pipeline_config_table

        await init_pipeline_config_table()
        await _ensure_defaults()
    except Exception as e:
        logger.warning("Failed to init pipeline config table", error=str(e))

    # 清理中断残留：容器重启前正在运行的 pipeline 标记为 interrupted
    try:
        from sqlalchemy import text

        async with db.session() as session:
            result = await session.execute(
                text(
                    "UPDATE projects SET status = 'interrupted' WHERE status LIKE 'running%' RETURNING id"
                )
            )
            stale = result.fetchall()
            if stale:
                pids = [str(r[0]) for r in stale]
                logger.info(
                    "Marked stale running projects as interrupted",
                    count=len(pids),
                    project_ids=pids,
                )
                await session.execute(
                    text(
                        "UPDATE pipeline_runs SET status = 'interrupted' WHERE project_id = ANY(:pids) AND status = 'running'"
                    ),
                    {"pids": pids},
                )
            await session.commit()
    except Exception as e:
        logger.warning("Failed to clean up stale running projects", error=str(e))

    yield

    # 清理资源
    logger.info("Shutting down application")
    from ..services.provider_pool import close_pools

    await close_pools()
    from ..graphs.graph import close_checkpointer

    await close_checkpointer()
    from ..services import close_cache, close_database, close_vector_store

    await close_database()
    await close_cache()
    await close_vector_store()


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    settings = get_settings()

    app = FastAPI(
        title="Academic Cluster",
        description="学术论文聚类与综述生成系统",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS 配置
    # 安全修复: 生产环境不允许 allow_origins=["*"] + allow_credentials=True 的组合
    # 该组合允许任意来源携带凭据发起跨域请求，存在 CSRF 风险
    if settings.cors_origins:
        cors_origins = [
            o.strip() for o in settings.cors_origins.split(",") if o.strip()
        ]
    elif settings.app_debug:
        cors_origins = ["*"]
    else:
        cors_origins = ["http://localhost:3000", "http://localhost:5173"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    # 注册路由
    from .admin import router as admin_router
    from .auth_routes import router as auth_router
    from .console import router as console_router
    from .routes import router
    from .sse import router as sse_router

    app.include_router(auth_router, prefix="/api")
    app.include_router(router, prefix="/api")
    app.include_router(sse_router, prefix="/api")
    app.include_router(console_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    return app


app = create_app()
