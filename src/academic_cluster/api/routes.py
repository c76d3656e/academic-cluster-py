"""
API 路由定义
"""

import asyncio
import contextlib
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..services.database import DatabaseService, get_database
from .dependencies import get_current_user

logger = structlog.get_logger()

router = APIRouter()

# 正在运行的 pipeline task 映射（project_id → asyncio.Task），用于暂停
_running_pipelines: dict[str, asyncio.Task[None]] = {}


@router.get("/features")
async def get_features(db: DatabaseService = Depends(get_database)) -> dict[str, Any]:
    """获取 UI 功能开关（无需登录）"""
    try:
        async with db.session() as session:
            r = await session.execute(
                text("SELECT key, value FROM pipeline_config WHERE key LIKE 'ui.%'")
            )
            rows = r.fetchall()
        return {row[0].replace("ui.", ""): (row[1] == "true") for row in rows}
    except Exception:
        return {"show_usage": False}


# =============================================================================
# 请求/响应模型
# =============================================================================


class CreateProjectRequest(BaseModel):
    """创建项目请求"""

    name: str = Field(..., min_length=1, max_length=255)
    query: str = Field(..., min_length=1, max_length=2000)
    description: str | None = Field(None, max_length=5000)
    config: dict[str, Any] | None = None


class ProjectResponse(BaseModel):
    """项目响应"""

    id: str
    name: str
    query: str
    status: str
    message: str


class PipelineStatusResponse(BaseModel):
    """Pipeline 状态响应"""

    project_id: str
    status: str
    current_node: str | None = None
    progress: dict[str, Any] | None = None
    error_message: str | None = None


class OutlineConfirmRequest(BaseModel):
    """大纲确认请求"""

    project_id: str
    approved: bool
    edited_outline: dict[str, Any] | None = None


class ProjectListItem(BaseModel):
    """项目列表项"""

    id: str
    name: str
    query: str
    status: str
    created_at: str | None = None


class ProjectListResponse(BaseModel):
    """项目列表响应"""

    projects: list[ProjectListItem]
    total: int


# =============================================================================
# 项目路由
# =============================================================================


@router.post("/projects", response_model=ProjectResponse)
async def create_project(
    request: CreateProjectRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> ProjectResponse:
    """创建新项目"""
    project_id = str(uuid.uuid4())

    logger.info(
        "Creating project",
        project_id=project_id,
        name=request.name,
        query=request.query,
        user_id=current_user["id"],
    )

    await db.save_project(
        {
            "id": project_id,
            "user_id": current_user["id"],
            "name": request.name,
            "query": request.query,
            "description": request.description,
            "config": request.config,
            "status": "created",
        }
    )

    return ProjectResponse(
        id=project_id,
        name=request.name,
        query=request.query,
        status="created",
        message="Project created successfully",
    )


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    skip: int = 0,
    limit: int = 20,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> ProjectListResponse:
    """列出项目"""
    # 安全修复: 限制分页参数范围，防止请求过大数据集
    skip = max(0, skip)
    limit = max(1, min(limit, 100))

    projects, total = await db.list_projects_by_user(current_user["id"], skip, limit)

    return ProjectListResponse(
        projects=[
            ProjectListItem(
                id=p["id"],
                name=p.get("name", ""),
                query=p.get("query", ""),
                status=p.get("status", "created"),
                created_at=str(p.get("created_at", "")),
            )
            for p in projects
        ],
        total=total,
    )


@router.get("/projects/{project_id}")
async def get_project_detail(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, Any]:
    """获取项目详情"""
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # 权限检查：只有项目所有者或管理员可以查看
    if (
        project.get("user_id") != current_user["id"]
        and current_user.get("role") != "admin"
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    return project


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, str]:
    """删除项目及关联的调用记录"""
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if (
        project.get("user_id") != current_user["id"]
        and current_user.get("role") != "admin"
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    from sqlalchemy import text

    async with db.session() as session:
        await session.execute(
            text("DELETE FROM projects WHERE id = :pid"), {"pid": project_id}
        )

    return {"message": "Project deleted"}


@router.get("/projects/{project_id}/status", response_model=PipelineStatusResponse)
async def get_project_status(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> PipelineStatusResponse:
    """获取项目状态"""
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if (
        project.get("user_id") != current_user["id"]
        and current_user.get("role") != "admin"
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    # 获取最近一次 pipeline run 的错误信息
    error_message = None
    if project.get("status") in ("failed", "interrupted"):
        from sqlalchemy import text

        async with db.session() as session:
            result = await session.execute(
                text("""
                    SELECT error_message FROM pipeline_runs
                    WHERE project_id = :pid AND error_message IS NOT NULL
                    ORDER BY created_at DESC LIMIT 1
                """),
                {"pid": project_id},
            )
            row = result.fetchone()
            if row and row[0]:
                error_message = row[0]

    return PipelineStatusResponse(
        project_id=project_id,
        status=project.get("status", "created"),
        current_node=None,
        error_message=error_message,
    )


@router.get("/projects/{project_id}/progress")
async def get_project_progress(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, Any]:
    """获取项目历史执行日志"""
    from sqlalchemy import text

    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if (
        project.get("user_id") != current_user["id"]
        and current_user.get("role") != "admin"
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    async with db.session() as session:
        rows = await session.execute(
            text("""
                SELECT ne.node_name, ne.status, ne.started_at, ne.finished_at,
                       ne.elapsed_ms, ne.error_message
                FROM node_executions ne
                JOIN pipeline_runs pr ON ne.pipeline_run_id = pr.id
                WHERE pr.project_id = :project_id
                ORDER BY COALESCE(ne.index, 0), ne.started_at
            """),
            {"project_id": project_id},
        )
        nodes = []
        for r in rows.fetchall():
            d = dict(r._mapping)
            for k in ("started_at", "finished_at"):
                if d.get(k):
                    d[k] = d[k].isoformat()
            nodes.append(d)

    return {"nodes": nodes}


# =============================================================================
# Pipeline 路由
# =============================================================================


@router.post("/pipeline/{project_id}/start")
async def start_pipeline(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, str]:
    """启动 Pipeline"""
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if (
        project.get("user_id") != current_user["id"]
        and current_user.get("role") != "admin"
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    # 防止并发启动
    if project_id in _running_pipelines:
        raise HTTPException(status_code=409, detail="Pipeline already running")

    logger.info("Starting pipeline", project_id=project_id)

    from ..graphs.graph import run_pipeline
    from .sse import get_sse_manager

    sse_manager = get_sse_manager()

    async def run_in_background() -> None:
        try:
            from .admin.pipeline_config import (
                build_node_config,
                get_pipeline_config_dict,
            )

            raw_config = await get_pipeline_config_dict()
            pipeline_config = build_node_config(raw_config)
            project_config = project.get("config") or {}
            pipeline_config.update(project_config)

            await run_pipeline(
                query=project.get("query", ""),
                project_id=project_id,
                config=pipeline_config,
                sse_manager=sse_manager,
            )
        except asyncio.CancelledError:
            logger.info("Pipeline cancelled", project_id=project_id)
            await db.update_project_status(project_id, "interrupted")
        except Exception as e:
            logger.error("Pipeline failed", error=str(e))
        finally:
            _running_pipelines.pop(project_id, None)

    task = asyncio.create_task(run_in_background())
    _running_pipelines[project_id] = task

    return {"message": "Pipeline started", "project_id": project_id}


@router.post("/pipeline/{project_id}/pause")
async def pause_pipeline(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, str]:
    """暂停 Pipeline（取消正在运行的 asyncio task，标记为 interrupted）"""
    task = _running_pipelines.get(project_id)
    if not task:
        raise HTTPException(status_code=400, detail="Pipeline not running")

    logger.info("Pausing pipeline", project_id=project_id)
    task.cancel()
    _running_pipelines.pop(project_id, None)
    await db.update_project_status(project_id, "interrupted")
    return {"message": "Pipeline paused", "project_id": project_id}


@router.post("/pipeline/{project_id}/resume")
async def resume_pipeline(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, str]:
    """从上次失败的检查点恢复 Pipeline"""
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if (
        project.get("user_id") != current_user["id"]
        and current_user.get("role") != "admin"
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    # 防止并发启动
    if project_id in _running_pipelines:
        raise HTTPException(status_code=409, detail="Pipeline already running")

    logger.info("Resuming pipeline from checkpoint", project_id=project_id)

    from ..graphs.graph import run_pipeline
    from .sse import get_sse_manager

    sse_manager = get_sse_manager()

    async def run_in_background() -> None:
        try:
            # 加载 pipeline 配置（DB 中的可调参数 + 项目自定义配置）
            from .admin.pipeline_config import (
                build_node_config,
                get_pipeline_config_dict,
            )

            raw_config = await get_pipeline_config_dict()
            pipeline_config = build_node_config(raw_config)
            project_config = project.get("config") or {}
            pipeline_config.update(project_config)

            await run_pipeline(
                query=project.get("query", ""),
                project_id=project_id,
                config=pipeline_config,
                sse_manager=sse_manager,
                resume=True,
            )
        except asyncio.CancelledError:
            logger.info("Pipeline resume cancelled", project_id=project_id)
            await db.update_project_status(project_id, "interrupted")
        except Exception as e:
            logger.error("Pipeline resume failed", error=str(e))
        finally:
            _running_pipelines.pop(project_id, None)

    task = asyncio.create_task(run_in_background())
    _running_pipelines[project_id] = task

    return {"message": "Pipeline resumed from checkpoint", "project_id": project_id}


# =============================================================================
# 大纲确认路由
# =============================================================================


@router.get("/projects/{project_id}/outline")
async def get_outline(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, Any]:
    """获取大纲"""
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if (
        project.get("user_id") != current_user["id"]
        and current_user.get("role") != "admin"
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    outline = await db.get_outline_by_project_id(project_id)

    return {
        "project_id": project_id,
        "outline": outline,
        "status": outline.get("status", "pending") if outline else "pending",
    }


@router.post("/projects/{project_id}/outline/confirm")
async def confirm_outline(
    project_id: str,
    request: OutlineConfirmRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    """确认大纲"""
    logger.info(
        "Confirming outline",
        project_id=project_id,
        approved=request.approved,
    )

    return {
        "message": "Outline confirmed" if request.approved else "Outline rejected",
        "project_id": project_id,
    }


# =============================================================================
# 结果路由
# =============================================================================


@router.get("/projects/{project_id}/review")
async def get_review(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, Any]:
    """获取综述"""
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if (
        project.get("user_id") != current_user["id"]
        and current_user.get("role") != "admin"
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    # 获取大纲
    outline = await db.get_outline_by_project_id(project_id)

    # 获取已写章节
    sections = await db.get_written_sections_by_project_id(project_id)

    # 按大纲顺序排序（并发写入导致 created_at 顺序可能与大纲不一致）
    if outline and sections:
        outline_sections = outline.get("sections") or []
        section_order = {
            str(s.get("name", s.get("number", i))): i
            for i, s in enumerate(outline_sections)
        }
        sections.sort(
            key=lambda s: section_order.get(str(s.get("section_id", "")), 999)
        )

    # 获取证据卡片
    evidence_cards = []
    if outline:
        # 获取该项目的证据卡片
        async with db.session() as session:
            from sqlalchemy import text

            result = await session.execute(
                text("""
                    SELECT DISTINCT ON (ec.id) ec.*
                    FROM evidence_cards ec
                    LEFT JOIN clusters c ON ec.cluster_id = c.id
                    WHERE ec.project_id = :project_id OR c.project_id = :project_id
                    ORDER BY ec.id, ec.created_at
                    LIMIT 200
                """),
                {"project_id": project_id},
            )
            rows = result.fetchall()
            evidence_cards = [dict(row._mapping) for row in rows]

    final_artifact = await db.get_pipeline_checkpoint(
        project_id, "final_review_artifact"
    )
    final_review = None
    abstract = None
    references: list[object] = []
    if final_artifact:
        snapshot = final_artifact.get("state_snapshot") or {}
        if isinstance(snapshot, str):
            import json as _json

            try:
                snapshot = _json.loads(snapshot)
            except (_json.JSONDecodeError, TypeError):
                snapshot = {}
        if isinstance(snapshot, dict):
            final_review = snapshot.get("final_review")
            abstract = snapshot.get("abstract")
            references = snapshot.get("references") or []

    return {
        "project_id": project_id,
        "outline": outline,
        "sections": sections,
        "evidence_cards": evidence_cards,
        "references": references,
        "final_review": final_review,
        "abstract": abstract,
        "status": project.get("status", "pending"),
    }


@router.get("/projects/{project_id}/visualization")
async def get_visualization(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, Any]:
    """获取社区可视化数据"""
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if (
        project.get("user_id") != current_user["id"]
        and current_user.get("role") != "admin"
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    visualization = await db.get_visualization_by_project_id(project_id)

    return {
        "project_id": project_id,
        "visualization": visualization,
    }


# =============================================================================
# 可观测性路由
# =============================================================================


@router.get("/runs/{run_id}/stats")
async def get_run_stats(
    run_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, Any]:
    """获取 Pipeline 运行统计"""
    stats = await db.get_pipeline_run_stats(run_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    return stats


@router.get("/runs/{run_id}/nodes")
async def get_run_nodes(
    run_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, Any]:
    """获取 Pipeline 运行的节点执行列表"""
    stats = await db.get_pipeline_run_stats(run_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    nodes = await db.get_node_executions(run_id)
    return {"run_id": run_id, "nodes": nodes}


@router.get("/runs/{run_id}/llm-calls")
async def get_run_llm_calls(
    run_id: str,
    node_name: str | None = None,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, Any]:
    """获取 Pipeline 运行的 LLM 调用记录"""
    stats = await db.get_pipeline_run_stats(run_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Pipeline run not found")
    calls = await db.get_llm_calls(run_id, node_name=node_name)
    return {"run_id": run_id, "llm_calls": calls}


@router.get("/usage/summary")
async def get_usage_summary(
    run_id: str | None = None,
    project_id: str | None = None,
    days: int = 30,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, Any]:
    """获取用量汇总（按 provider/model 分组）"""
    summary = await db.get_provider_usage_summary(
        run_id=run_id,
        project_id=project_id,
        days=days,
    )
    return {"days": days, "summary": summary}


# =============================================================================
# WebSocket 路由（实时更新）
# =============================================================================


class ConnectionManager:
    """WebSocket 连接管理"""

    def __init__(self) -> None:
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, project_id: str) -> None:
        await websocket.accept()
        if project_id not in self.active_connections:
            self.active_connections[project_id] = []
        self.active_connections[project_id].append(websocket)

    def disconnect(self, websocket: WebSocket, project_id: str) -> None:
        if project_id in self.active_connections:
            self.active_connections[project_id].remove(websocket)

    async def send_update(self, project_id: str, data: dict[str, Any]) -> None:
        if project_id in self.active_connections:
            for connection in self.active_connections[project_id]:
                with contextlib.suppress(Exception):
                    await connection.send_json(data)


manager = ConnectionManager()


@router.websocket("/ws/{project_id}")
async def websocket_endpoint(
    websocket: WebSocket, project_id: str, token: str | None = None
) -> None:
    """WebSocket 端点，用于实时更新"""
    # 安全修复: WebSocket 连接必须携带有效 token（通过 query 参数传递）
    from ..services.auth import get_token_service

    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        return

    token_service = get_token_service()
    try:
        payload = token_service.decode_access_token(token)
    except ValueError:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    db = get_database()
    user = await db.get_user_by_id(payload["sub"])
    if not user or not user.get("is_active", False):
        await websocket.close(code=4001, reason="User not found or deactivated")
        return

    # 权限检查: 验证用户有权访问该项目
    project = await db.get_project(project_id)
    if project and project.get("user_id") != user["id"] and user.get("role") != "admin":
        await websocket.close(code=4003, reason="Access denied")
        return

    await manager.connect(websocket, project_id)
    try:
        while True:
            await websocket.receive_text()
            logger.info("WebSocket message received", project_id=project_id)
    except WebSocketDisconnect:
        manager.disconnect(websocket, project_id)
