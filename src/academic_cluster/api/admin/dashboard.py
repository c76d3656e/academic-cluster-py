"""
管理后台 - 仪表盘

提供系统概览统计数据。
"""

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from ...services.database import DatabaseService, get_database
from ..dependencies import require_admin

logger = structlog.get_logger()

router = APIRouter(tags=["admin-dashboard"])


# =============================================================================
# 响应模型
# =============================================================================


class ProviderSummary(BaseModel):
    """Provider 概览"""

    id: str
    name: str
    status: str
    total_calls: int = 0
    total_cost: float = 0.0


class DailyUsageItem(BaseModel):
    """每日用量"""

    date: str
    calls: int = 0
    tokens: int = 0
    cost: float = 0.0


class ActivityItem(BaseModel):
    """最近活动"""

    id: str
    user_id: str
    action: str
    resource_type: str | None = None
    created_at: str | None = None


class AdminOverviewResponse(BaseModel):
    """管理后台概览响应"""

    total_users: int
    active_users: int
    total_projects: int
    running_projects: int = 0
    total_papers: int
    total_runs: int = 0
    total_llm_calls: int = 0
    total_cost: float = 0.0
    total_tokens: int = 0
    providers: list[ProviderSummary] = []
    recent_activities: list[ActivityItem] = []
    daily_usage: list[DailyUsageItem] = []


# =============================================================================
# 端点
# =============================================================================


@router.get("/overview", response_model=AdminOverviewResponse)
async def admin_overview(
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """获取管理后台概览数据"""
    stats = await db.get_system_stats()

    # 获取 Provider 状态
    providers = []
    try:
        async with db.session() as session:
            result = await session.execute(
                text("""
                    SELECT pr.id, pr.display_name, pr.health_status,
                           COUNT(lc.id) AS total_calls,
                           COALESCE(SUM(lc.cost), 0) AS total_cost
                    FROM provider_registry pr
                    LEFT JOIN llm_calls lc ON lc.provider_name = pr.display_name
                    WHERE pr.is_enabled = true
                    GROUP BY pr.id, pr.display_name, pr.health_status
                    ORDER BY pr.priority DESC
                    LIMIT 10
                """),
            )
            rows = result.fetchall()
            providers = [
                ProviderSummary(
                    id=str(row[0]),
                    name=row[1],
                    status=row[2] or "unknown",
                    total_calls=row[3] or 0,
                    total_cost=float(row[4]) or 0.0,
                )
                for row in rows
            ]
    except Exception as e:
        logger.debug("Failed to fetch provider summary", error=str(e))

    # 获取最近活动
    activities = []
    try:
        async with db.session() as session:
            result = await session.execute(
                text("""
                    SELECT id, user_id, action, resource_type, created_at
                    FROM user_activities
                    ORDER BY created_at DESC
                    LIMIT 10
                """),
            )
            rows = result.fetchall()
            activities = [
                ActivityItem(
                    id=str(row[0]),
                    user_id=str(row[1]),
                    action=row[2],
                    resource_type=row[3],
                    created_at=str(row[4]) if row[4] else None,
                )
                for row in rows
            ]
    except Exception as e:
        logger.debug("Failed to fetch recent activities", error=str(e))

    # 获取每日用量（近 30 天）
    daily_usage = []
    try:
        async with db.session() as session:
            result = await session.execute(
                text("""
                    SELECT
                        DATE(created_at) AS date,
                        COUNT(*) AS calls,
                        COALESCE(SUM(total_tokens), 0) AS tokens,
                        COALESCE(SUM(cost), 0) AS cost
                    FROM llm_calls
                    WHERE created_at >= NOW() - INTERVAL '30 days'
                    GROUP BY DATE(created_at)
                    ORDER BY date DESC
                """),
            )
            rows = result.fetchall()
            daily_usage = [
                DailyUsageItem(
                    date=str(row[0]),
                    calls=row[1],
                    tokens=int(row[2]),
                    cost=float(row[3]),
                )
                for row in rows
            ]
    except Exception as e:
        logger.debug("Failed to fetch daily usage", error=str(e))

    return AdminOverviewResponse(
        total_users=stats["total_users"],
        active_users=stats["active_users"],
        total_projects=stats["total_projects"],
        running_projects=stats.get("running_projects", 0),
        total_papers=stats["total_papers"],
        total_runs=stats.get("total_runs", 0),
        total_llm_calls=stats.get("total_llm_calls", 0),
        total_cost=stats.get("total_cost", 0.0),
        total_tokens=stats.get("total_tokens", 0),
        providers=providers,
        recent_activities=activities,
        daily_usage=daily_usage,
    )
