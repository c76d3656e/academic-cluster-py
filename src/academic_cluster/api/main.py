"""
FastAPI 主应用
"""

import structlog
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..config import get_settings

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("Starting application")

    # 安全校验: 生产环境检查配置是否安全
    settings = get_settings()
    settings.validate_security()

    # 初始化服务
    from ..services import get_database, get_cache, get_vector_store
    db = get_database()
    cache = get_cache()
    vector_store = get_vector_store()

    # 初始化 LangGraph checkpointer（AsyncPostgresSaver）
    try:
        from ..graphs.graph import get_checkpointer
        await get_checkpointer()
    except Exception as e:
        logger.warning("Failed to init AsyncPostgresSaver, will use MemorySaver fallback", error=str(e))

    # 初始化 Provider Pool（LiteLLM Router）
    try:
        from ..services.provider_pool import init_pools
        await init_pools()
    except Exception as e:
        logger.warning("Failed to init provider pools", error=str(e))

    yield

    # 清理资源
    logger.info("Shutting down application")
    from ..services.provider_pool import close_pools
    await close_pools()
    from ..graphs.graph import close_checkpointer
    await close_checkpointer()
    from ..services import close_database, close_cache, close_vector_store
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
        cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
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
    from .routes import router
    from .sse import router as sse_router
    from .auth_routes import router as auth_router
    app.include_router(auth_router, prefix="/api")
    app.include_router(router, prefix="/api")
    app.include_router(sse_router, prefix="/api")

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    return app


app = create_app()
