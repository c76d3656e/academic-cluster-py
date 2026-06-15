"""
Console API 路由

提供用户控制台相关的端点（仪表盘、用量、个人资料）。
"""

from fastapi import APIRouter

from .dashboard import router as dashboard_router
from .profile import router as profile_router
from .usage import router as usage_router

router = APIRouter(prefix="/console", tags=["console"])

router.include_router(dashboard_router)
router.include_router(profile_router)
router.include_router(usage_router)
