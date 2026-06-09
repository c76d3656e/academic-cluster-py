"""
API 路由定义
"""

import uuid

import structlog
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from ..config import get_settings

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# 请求/响应模型
# =============================================================================

class CreateProjectRequest(BaseModel):
    """创建项目请求"""
    name: str
    query: str
    description: str | None = None
    config: dict | None = None


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
    progress: dict | None = None


class OutlineConfirmRequest(BaseModel):
    """大纲确认请求"""
    project_id: str
    approved: bool
    edited_outline: dict | None = None


# =============================================================================
# 项目路由
# =============================================================================

@router.post("/projects", response_model=ProjectResponse)
async def create_project(request: CreateProjectRequest):
    """创建新项目"""
    project_id = str(uuid.uuid4())

    logger.info(
        "Creating project",
        project_id=project_id,
        name=request.name,
        query=request.query,
    )

    # TODO: 启动 Pipeline

    return ProjectResponse(
        id=project_id,
        name=request.name,
        query=request.query,
        status="created",
        message="Project created successfully",
    )


@router.get("/projects/{project_id}", response_model=PipelineStatusResponse)
async def get_project_status(project_id: str):
    """获取项目状态"""
    # TODO: 从数据库获取项目状态

    return PipelineStatusResponse(
        project_id=project_id,
        status="created",
        current_node=None,
    )


# =============================================================================
# Pipeline 路由
# =============================================================================

@router.post("/pipeline/{project_id}/start")
async def start_pipeline(project_id: str):
    """启动 Pipeline"""
    logger.info("Starting pipeline", project_id=project_id)

    # TODO: 启动 Pipeline 执行

    return {"message": "Pipeline started", "project_id": project_id}


@router.post("/pipeline/{project_id}/pause")
async def pause_pipeline(project_id: str):
    """暂停 Pipeline"""
    logger.info("Pausing pipeline", project_id=project_id)

    # TODO: 暂停 Pipeline

    return {"message": "Pipeline paused", "project_id": project_id}


@router.post("/pipeline/{project_id}/resume")
async def resume_pipeline(project_id: str):
    """恢复 Pipeline"""
    logger.info("Resuming pipeline", project_id=project_id)

    # TODO: 恢复 Pipeline

    return {"message": "Pipeline resumed", "project_id": project_id}


# =============================================================================
# 大纲确认路由
# =============================================================================

@router.get("/projects/{project_id}/outline")
async def get_outline(project_id: str):
    """获取大纲"""
    # TODO: 从数据库获取大纲

    return {
        "project_id": project_id,
        "outline": None,
        "status": "pending",
    }


@router.post("/projects/{project_id}/outline/confirm")
async def confirm_outline(project_id: str, request: OutlineConfirmRequest):
    """确认大纲"""
    logger.info(
        "Confirming outline",
        project_id=project_id,
        approved=request.approved,
    )

    # TODO: 恢复 Pipeline 执行

    return {
        "message": "Outline confirmed" if request.approved else "Outline rejected",
        "project_id": project_id,
    }


# =============================================================================
# 结果路由
# =============================================================================

@router.get("/projects/{project_id}/review")
async def get_review(project_id: str):
    """获取综述"""
    # TODO: 从数据库获取综述

    return {
        "project_id": project_id,
        "review": None,
        "bibtex": None,
        "status": "pending",
    }


@router.get("/projects/{project_id}/visualization")
async def get_visualization(project_id: str):
    """获取社区可视化数据"""
    # TODO: 从数据库获取可视化数据

    return {
        "project_id": project_id,
        "visualization": None,
    }


# =============================================================================
# WebSocket 路由（实时更新）
# =============================================================================

class ConnectionManager:
    """WebSocket 连接管理"""

    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, project_id: str):
        await websocket.accept()
        if project_id not in self.active_connections:
            self.active_connections[project_id] = []
        self.active_connections[project_id].append(websocket)

    def disconnect(self, websocket: WebSocket, project_id: str):
        if project_id in self.active_connections:
            self.active_connections[project_id].remove(websocket)

    async def send_update(self, project_id: str, data: dict):
        if project_id in self.active_connections:
            for connection in self.active_connections[project_id]:
                try:
                    await connection.send_json(data)
                except Exception:
                    pass


manager = ConnectionManager()


@router.websocket("/ws/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    """WebSocket 端点，用于实时更新"""
    await manager.connect(websocket, project_id)
    try:
        while True:
            data = await websocket.receive_text()
            # 处理客户端消息
            logger.info("WebSocket message received", project_id=project_id)
    except WebSocketDisconnect:
        manager.disconnect(websocket, project_id)
