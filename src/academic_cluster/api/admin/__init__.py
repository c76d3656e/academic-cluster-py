"""
管理后台路由模块

汇总所有管理后台子路由，对外暴露统一的 /admin 前缀路由。
"""

from fastapi import APIRouter

from .dashboard import router as dashboard_router
from .users import router as users_router
from .projects import router as projects_router
from .providers import router as providers_router
from .usage import router as usage_router
from .audit import router as audit_router
from .source_config import router as source_config_router
from .pipeline_config import router as pipeline_config_router

router = APIRouter(prefix="/admin")

router.include_router(dashboard_router, tags=["admin-dashboard"])
router.include_router(users_router, prefix="/users", tags=["admin-users"])
router.include_router(projects_router, prefix="/projects", tags=["admin-projects"])
router.include_router(providers_router, prefix="/providers", tags=["admin-providers"])
router.include_router(usage_router, prefix="/usage", tags=["admin-usage"])
router.include_router(audit_router, prefix="/audit", tags=["admin-audit"])
router.include_router(source_config_router, tags=["admin-source-config"])
router.include_router(pipeline_config_router, tags=["admin-pipeline-config"])
