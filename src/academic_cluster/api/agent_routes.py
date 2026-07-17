"""
Agent API 路由

提供多智能体系统的 HTTP 端点，包括启动 Agent 执行、查询状态和获取决策日志。
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from ..services.agent_runtime import (
    AgentAlreadyRunningError,
    AgentCheckpointNotFoundError,
    AgentNotRunningError,
    AgentRuntimeUnavailableError,
    get_agent_run_manager,
    resolve_agent_targets,
)
from ..services.database import DatabaseService, get_database
from .dependencies import get_current_user

router = APIRouter()


# =============================================================================
# 请求/响应模型
# =============================================================================


class RunAgentRequest(BaseModel):
    """启动 Agent 执行请求"""

    project_id: str
    target_papers: int = Field(50, ge=1, le=500, strict=True)
    target_words: int = Field(12000, ge=1000, le=100000, strict=True)


class RunAgentResponse(BaseModel):
    """启动 Agent 执行响应"""

    message: str
    project_id: str
    execution_id: str


class AgentStatusResponse(BaseModel):
    """Agent 执行状态响应"""

    execution_id: str
    agent_name: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    duration_ms: int | None = None
    quality_score: float | None = None
    error_message: str | None = None


class AgentDecisionItem(BaseModel):
    """Agent 决策记录"""

    id: str
    execution_id: str
    agent_name: str
    decision_type: str
    reasoning: str | None = None
    created_at: str | None = None


class AgentToolCallItem(BaseModel):
    """Agent 工具调用记录"""

    id: str
    execution_id: str
    agent_name: str
    tool_name: str
    input_summary: str | None = None
    output_summary: str | None = None
    duration_ms: int | None = None
    status: str
    error_message: str | None = None
    created_at: str | None = None


class AgentLogsResponse(BaseModel):
    """Agent 日志响应"""

    project_id: str
    decisions: list[AgentDecisionItem]
    tool_calls: list[AgentToolCallItem]


# =============================================================================
# 辅助函数
# =============================================================================


async def _verify_project_access(
    project_id: str,
    current_user: dict[str, Any],
    db: DatabaseService,
) -> dict[str, Any]:
    """验证项目存在且当前用户有访问权限，返回项目对象"""
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if (
        project.get("user_id") != current_user["id"]
        and current_user.get("role") != "admin"
    ):
        raise HTTPException(status_code=403, detail="Access denied")

    return project


async def _start_managed_agent(
    *,
    project: dict[str, Any],
    target_papers: int,
    target_words: int,
    db: DatabaseService,
    resume: bool,
) -> str:
    from .sse import get_sse_manager

    try:
        return await get_agent_run_manager().start(
            project=project,
            target_papers=target_papers,
            target_words=target_words,
            sse_manager=get_sse_manager(),
            resume=resume,
            db=db,
        )
    except AgentAlreadyRunningError as error:
        raise HTTPException(
            status_code=409,
            detail="Agent already running for this project",
        ) from error
    except AgentCheckpointNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except AgentRuntimeUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


# =============================================================================
# Agent 路由
# =============================================================================


@router.get("/agent/contracts")
async def get_agent_contracts(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the versioned, machine-readable contract registry."""

    del current_user  # Authentication is the access boundary; contracts are static.
    from ..agents.node_contracts import export_contract_manifest

    return export_contract_manifest()


@router.get("/agent/contracts/{node_name}")
async def get_agent_contract(
    node_name: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Return one node contract and its exact input/output Artifact schemas."""

    del current_user
    from ..agents.node_contracts import export_contract_manifest, get_node_contract

    try:
        get_node_contract(node_name)
    except ValueError as error:
        raise HTTPException(status_code=404, detail="Unknown Agent node") from error
    manifest = export_contract_manifest()
    return next(entry for entry in manifest["nodes"] if entry["node"] == node_name)


@router.post("/agent/run", response_model=RunAgentResponse)
async def run_agent(
    request: RunAgentRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> RunAgentResponse:
    """启动由唯一运行管理器托管的 Agent 执行。"""
    project = await _verify_project_access(request.project_id, current_user, db)
    execution_id = await _start_managed_agent(
        project=project,
        target_papers=request.target_papers,
        target_words=request.target_words,
        db=db,
        resume=False,
    )
    return RunAgentResponse(
        message="Agent started with checkpoint support",
        project_id=request.project_id,
        execution_id=execution_id,
    )


@router.get("/agent/{project_id}/status", response_model=AgentStatusResponse)
async def get_agent_status(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> AgentStatusResponse:
    """获取指定项目最近一次 Agent 执行的状态"""
    await _verify_project_access(project_id, current_user, db)
    execution = await db.get_latest_agent_execution(project_id)
    if not execution:
        raise HTTPException(
            status_code=404, detail="No agent execution found for this project"
        )

    for k in ("started_at", "finished_at"):
        value = execution.get(k)
        if value is not None and hasattr(value, "isoformat"):
            execution[k] = value.isoformat()

    public_status = {
        "pending": "running",
        "succeeded": "completed",
        "cancelled": "interrupted",
    }.get(str(execution.get("status") or ""), str(execution.get("status") or "unknown"))
    return AgentStatusResponse(
        execution_id=str(execution["id"]),
        agent_name=str(execution.get("agent_name") or "orchestrator"),
        status=public_status,
        started_at=execution.get("started_at"),
        finished_at=execution.get("finished_at"),
        duration_ms=execution.get("duration_ms"),
        quality_score=execution.get("quality_score"),
        error_message=execution.get("error_message"),
    )


class ResumeAgentResponse(BaseModel):
    """Agent 恢复响应"""

    message: str
    project_id: str
    execution_id: str


@router.post("/agent/{project_id}/resume", response_model=ResumeAgentResponse)
async def resume_agent(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> ResumeAgentResponse:
    """按 checkpoint 状态恢复、协调终态或创建可追踪的新执行。"""
    project = await _verify_project_access(project_id, current_user, db)
    target_papers, target_words = resolve_agent_targets(project.get("config"))
    execution_id = await _start_managed_agent(
        project=project,
        target_papers=target_papers,
        target_words=target_words,
        db=db,
        resume=True,
    )
    return ResumeAgentResponse(
        message="Agent resume or retry accepted",
        project_id=project_id,
        execution_id=execution_id,
    )


@router.post("/agent/{project_id}/pause")
async def pause_agent(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, str]:
    """暂停当前执行并等待其持久化 interrupted 状态。"""

    await _verify_project_access(project_id, current_user, db)
    execution = await db.get_latest_agent_execution(project_id)
    try:
        await get_agent_run_manager().cancel(project_id)
    except AgentNotRunningError as error:
        raise HTTPException(status_code=409, detail="Agent not running") from error
    if not execution:
        raise HTTPException(status_code=409, detail="Agent execution not found")
    return {
        "message": "Agent paused",
        "project_id": project_id,
        "execution_id": str(execution["id"]),
    }


@router.get("/agent/{project_id}/logs", response_model=AgentLogsResponse)
async def get_agent_logs(
    project_id: str,
    limit: int = 50,
    offset: int = 0,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> AgentLogsResponse:
    """获取指定项目的 Agent 决策日志和工具调用记录"""
    await _verify_project_access(project_id, current_user, db)

    # 安全修复: 限制分页参数范围
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    async with db.session() as session:
        # 查询决策记录
        decisions_result = await session.execute(
            text("""
                SELECT ad.id, ad.execution_id, ad.agent_name,
                       ad.decision AS decision_type,
                       ad.reason AS reasoning, ad.created_at
                FROM agent_decisions ad
                WHERE ad.project_id = :project_id
                ORDER BY ad.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"project_id": project_id, "limit": limit, "offset": offset},
        )
        decision_rows = decisions_result.fetchall()

        # 查询工具调用记录
        tool_calls_result = await session.execute(
            text("""
                SELECT atc.id, atc.execution_id, atc.agent_name, atc.tool_name,
                       atc.input_summary, atc.output_summary,
                       atc.duration_ms, atc.status, atc.error_message,
                       atc.created_at
                FROM agent_tool_calls atc
                WHERE atc.project_id = :project_id
                ORDER BY atc.created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {"project_id": project_id, "limit": limit, "offset": offset},
        )
        tool_call_rows = tool_calls_result.fetchall()

    decisions = []
    for row in decision_rows:
        d = dict(row._mapping)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        decisions.append(
            AgentDecisionItem(
                id=str(d["id"]),
                execution_id=str(d["execution_id"]),
                agent_name=d.get("agent_name", ""),
                decision_type=d.get("decision_type", ""),
                reasoning=d.get("reasoning"),
                created_at=d.get("created_at"),
            )
        )

    tool_calls = []
    for row in tool_call_rows:
        d = dict(row._mapping)
        if d.get("created_at"):
            d["created_at"] = d["created_at"].isoformat()
        tool_calls.append(
            AgentToolCallItem(
                id=str(d["id"]),
                execution_id=str(d["execution_id"]),
                agent_name=d.get("agent_name", ""),
                tool_name=d.get("tool_name", ""),
                input_summary=d.get("input_summary"),
                output_summary=d.get("output_summary"),
                duration_ms=d.get("duration_ms"),
                status=d.get("status", "unknown"),
                error_message=d.get("error_message"),
                created_at=d.get("created_at"),
            )
        )

    return AgentLogsResponse(
        project_id=project_id,
        decisions=decisions,
        tool_calls=tool_calls,
    )
