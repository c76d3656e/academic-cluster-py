"""
Console 仪表盘路由

提供用户控制台概览数据。
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from ...services.database import DatabaseService, get_database
from ..dependencies import get_current_user

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# 响应模型
# =============================================================================


class RecentProject(BaseModel):
    """最近项目"""

    id: str
    name: str
    status: str
    created_at: datetime | None = None


class DailyUsageItem(BaseModel):
    """每日用量"""

    date: str
    token_count: int = 0
    cost: float = 0.0


class DashboardOverview(BaseModel):
    """仪表盘概览响应"""

    project_count: int
    running_projects: int
    total_papers: int
    total_tokens: int
    total_cost: float
    recent_projects: list[RecentProject]
    daily_usage: list[DailyUsageItem]


# =============================================================================
# 端点
# =============================================================================


@router.get("/overview", response_model=DashboardOverview)
async def get_dashboard_overview(
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
):
    """获取用户仪表盘概览数据"""
    user_id = current_user["id"]

    async with db.session() as session:
        # 项目总数
        result = await session.execute(
            text("SELECT COUNT(*) FROM projects WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        project_count = result.scalar() or 0

        # 运行中的项目数
        result = await session.execute(
            text(
                "SELECT COUNT(*) FROM projects WHERE user_id = :user_id AND status LIKE 'running%'"
            ),
            {"user_id": user_id},
        )
        running_projects = result.scalar() or 0

        # 用户项目的论文总数（通过 clusters 关联）
        result = await session.execute(
            text("""
                SELECT COUNT(DISTINCT ca.paper_id)
                FROM cluster_assignments ca
                JOIN clusters c ON ca.cluster_id = c.id
                WHERE c.project_id IN (
                    SELECT id FROM projects WHERE user_id = :user_id
                )
            """),
            {"user_id": user_id},
        )
        total_papers = result.scalar() or 0

        # 用户项目 pipeline_runs 的总 token 和总费用
        result = await session.execute(
            text("""
                SELECT
                    COALESCE(SUM(pr.total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(pr.total_cost), 0) AS total_cost
                FROM pipeline_runs pr
                WHERE pr.project_id IN (
                    SELECT id FROM projects WHERE user_id = :user_id
                )
            """),
            {"user_id": user_id},
        )
        row = result.fetchone()
        total_tokens = int(row[0]) if row else 0
        total_cost = float(row[1]) if row else 0.0

        # 最近 5 个项目
        result = await session.execute(
            text("""
                SELECT id, name, status, created_at
                FROM projects
                WHERE user_id = :user_id
                ORDER BY created_at DESC
                LIMIT 5
            """),
            {"user_id": user_id},
        )
        recent_rows = result.fetchall()

    recent_projects = [
        RecentProject(
            id=str(row[0]),
            name=row[1] or "",
            status=row[2] or "created",
            created_at=row[3],
        )
        for row in recent_rows
    ]

    return DashboardOverview(
        project_count=project_count,
        running_projects=running_projects,
        total_papers=total_papers,
        total_tokens=total_tokens,
        total_cost=total_cost,
        recent_projects=recent_projects,
        daily_usage=[],
    )
