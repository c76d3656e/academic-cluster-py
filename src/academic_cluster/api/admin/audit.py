"""
管理后台 - 审计日志

提供用户活动日志查询端点。
"""

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from ...services.database import DatabaseService, get_database
from ..dependencies import require_admin

logger = structlog.get_logger()

router = APIRouter(tags=["admin-audit"])


# =============================================================================
# 响应模型
# =============================================================================


class AuditLogItem(BaseModel):
    """审计日志条目"""

    id: str
    user_id: str
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    details: dict | None = None
    ip_address: str | None = None
    created_at: str | None = None


class AuditLogListResponse(BaseModel):
    """审计日志列表响应"""

    logs: list[AuditLogItem]
    total: int


# =============================================================================
# 端点
# =============================================================================


@router.get("/logs", response_model=AuditLogListResponse)
async def get_audit_logs(
    user_id: str | None = None,
    action: str | None = None,
    skip: int = 0,
    limit: int = 50,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """查询用户活动日志

    支持按 user_id 和 action 过滤，分页查询。
    """
    import json

    skip = max(0, skip)
    limit = max(1, min(limit, 200))

    # 构建动态查询条件
    conditions = []
    params: dict = {"limit": limit, "skip": skip}

    if user_id:
        conditions.append("ua.user_id = :user_id")
        params["user_id"] = user_id
    if action:
        conditions.append("ua.action = :action")
        params["action"] = action

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    async with db.session() as session:
        # 查询总数
        count_result = await session.execute(
            text(f"SELECT COUNT(*) FROM user_activities ua {where_clause}"),  # nosec B608
            params,
        )
        total = count_result.scalar()

        # 查询数据
        result = await session.execute(
            text(f"""
                SELECT ua.id, ua.user_id, ua.action, ua.resource_type,
                       ua.resource_id, ua.details, ua.ip_address, ua.created_at
                FROM user_activities ua
                {where_clause}
                ORDER BY ua.created_at DESC
                LIMIT :limit OFFSET :skip
            """),  # nosec B608
            params,
        )
        rows = result.fetchall()

    logs = []
    for row in rows:
        details = row[5]
        if isinstance(details, str):
            try:
                details = json.loads(details)
            except (json.JSONDecodeError, TypeError):
                details = None

        logs.append(
            AuditLogItem(
                id=str(row[0]),
                user_id=str(row[1]),
                action=row[2],
                resource_type=row[3],
                resource_id=str(row[4]) if row[4] else None,
                details=details,
                ip_address=row[6],
                created_at=str(row[7]) if row[7] else None,
            )
        )

    return AuditLogListResponse(logs=logs, total=total)
