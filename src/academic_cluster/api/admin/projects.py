"""
管理后台 - 项目管理

提供项目列表、删除等管理端点。
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ...services.database import DatabaseService, get_database
from ..dependencies import require_admin

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
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
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
                status=p.get("status", "created"),
                user_id=p.get("user_id"),
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
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """删除项目"""
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 使用原始 SQL 级联删除项目及相关数据
    from sqlalchemy import text

    async with db.session() as session:
        # 删除相关的 LLM 调用记录
        await session.execute(
            text("""
                DELETE FROM llm_calls
                WHERE pipeline_run_id IN (
                    SELECT id FROM pipeline_runs WHERE project_id = :project_id
                )
            """),
            {"project_id": project_id},
        )

        # 删除相关的节点执行记录
        await session.execute(
            text("""
                DELETE FROM node_executions
                WHERE pipeline_run_id IN (
                    SELECT id FROM pipeline_runs WHERE project_id = :project_id
                )
            """),
            {"project_id": project_id},
        )

        # 删除 pipeline 运行记录
        await session.execute(
            text("DELETE FROM pipeline_runs WHERE project_id = :project_id"),
            {"project_id": project_id},
        )

        # 删除审计日志
        await session.execute(
            text("DELETE FROM pipeline_audit_log WHERE project_id = :project_id"),
            {"project_id": project_id},
        )

        # 删除大纲
        await session.execute(
            text("DELETE FROM outlines WHERE project_id = :project_id"),
            {"project_id": project_id},
        )

        # 删除项目
        await session.execute(
            text("DELETE FROM projects WHERE id = :project_id"),
            {"project_id": project_id},
        )

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
