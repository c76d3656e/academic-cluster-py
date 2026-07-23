"""
管理后台 - 项目管理

提供项目列表、删除等管理端点。
"""

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...services.database import DatabaseService, get_database
from ..dependencies import require_admin
from ..routes import normalize_project_status

logger = structlog.get_logger()

router = APIRouter(tags=["admin-projects"])


# =============================================================================
# 响应模型
# =============================================================================


class AdminProjectItem(BaseModel):
    """管理后台项目列表项"""

    id: str
    name: str
    query: str
    status: str
    user_id: str | None = None
    user_name: str | None = None
    user_email: str | None = None
    created_at: str | None = None


class AdminProjectListResponse(BaseModel):
    """管理后台项目列表响应"""

    projects: list[AdminProjectItem]
    total: int


# =============================================================================
# 端点
# =============================================================================


@router.get("", response_model=AdminProjectListResponse)
async def list_all_projects(
    skip: int = 0,
    limit: int = 20,
    admin: dict[str, Any] = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
) -> AdminProjectListResponse:
    """列出所有项目"""
    skip = max(0, skip)
    limit = max(1, min(limit, 100))

    projects, total = await db.list_all_projects(skip, limit)

    return AdminProjectListResponse(
        projects=[
            AdminProjectItem(
                id=p["id"],
                name=p.get("name", ""),
                query=p.get("query", ""),
                status=normalize_project_status(p.get("status"))[0],
                user_id=p.get("user_id"),
                user_name=p.get("user_name"),
                user_email=p.get("user_email"),
                created_at=str(p.get("created_at", "")),
            )
            for p in projects
        ],
        total=total,
    )


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    request: Request,
    admin: dict[str, Any] = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
) -> dict[str, str]:
    """删除项目"""
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from ...services.project_cleanup import delete_project_data

    await delete_project_data(project_id, db)

    await db.log_activity(
        admin["id"],
        "admin_delete_project",
        "project",
        project_id,
        {"name": project.get("name", "")},
        ip_address=request.client.host if request.client else None,
    )

    logger.info("Admin deleted project", admin_id=admin["id"], project_id=project_id)
    return {"message": "项目已删除"}
