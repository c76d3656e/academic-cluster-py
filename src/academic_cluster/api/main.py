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

    # 初始化服务
    from ..services import get_database, get_cache, get_vector_store
    db = get_database()
    cache = get_cache()
    vector_store = get_vector_store()

    yield

    # 清理资源
    logger.info("Shutting down application")
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
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    from .routes import router
    app.include_router(router, prefix="/api")

    @app.get("/health")
    async def health():
        return {"status": "healthy"}

    return app


app = create_app()
