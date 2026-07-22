"""
API 路由定义
"""

import json
import re
import uuid
from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import text

from ..config import get_settings
from ..services.agent_runtime import (
    AgentAlreadyRunningError,
    AgentCancellationTimeoutError,
    AgentCheckpointNotFoundError,
    AgentNotRunningError,
    AgentQueueFullError,
    AgentRuntimeUnavailableError,
    get_agent_run_manager,
    resolve_agent_targets,
)
from ..services.database import DatabaseService, get_database
from .dependencies import get_current_user, project_access_allowed

logger = structlog.get_logger()

router = APIRouter()

_LEGACY_RUNNING_PHASES = {
    "searching": "research",
    "filtering": "research",
    "embedding": "analysis",
    "clustering": "analysis",
    "extracting_kg": "analysis",
    "generating_evidence": "analysis",
    "analyzing_gaps": "analysis",
    "outlining": "writing",
    "writing": "writing",
    "reviewing": "peer_review",
}


def normalize_project_status(raw_status: object) -> tuple[str, str | None]:
    """Map every persisted legacy/internal status to the public five-state API."""

    raw = str(raw_status or "created")
    if raw.startswith("running:agent:"):
        return "running", raw.removeprefix("running:agent:") or None
    if raw.startswith("running"):
        return "running", None
    if raw in _LEGACY_RUNNING_PHASES:
        return "running", _LEGACY_RUNNING_PHASES[raw]
    canonical = {
        "created": "pending",
        "pending": "pending",
        "completed": "completed",
        "succeeded": "completed",
        "failed": "failed",
        "interrupted": "interrupted",
        "cancelled": "interrupted",
        "confirming_outline": "interrupted",
    }
    return canonical.get(raw, "pending"), None


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

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    query: str = Field(..., min_length=1, max_length=2000)
    description: str | None = Field(None, max_length=5000)
    config: dict[str, Any] | None = None

    @field_validator("config")
    @classmethod
    def validate_config_size(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        if len(encoded) > get_settings().max_project_config_bytes:
            raise ValueError("project config exceeds the configured size limit")
        return value


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
    execution_id: str | None = None
    status: str
    current_phase: str | None = None
    current_node: str | None = None
    progress: dict[str, Any] | None = None
    error_message: str | None = None


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


class ProjectSourcePaperResponse(BaseModel):
    """One project-owned paper exposed by the source ledger."""

    id: str
    title: str
    authors: list[Any] | str = Field(default_factory=list)
    year: int | str | date | None = None
    journal: str | None = None
    doi: str | None = None
    url: str | None = None
    citation_count: int = 0


class ProjectSourceSummaryResponse(BaseModel):
    """Project papers grouped by their persisted academic source."""

    source: str
    count: int
    papers: list[ProjectSourcePaperResponse]


class ProjectSourcesResponse(BaseModel):
    """Complete source-ledger response for one authorized project."""

    project_id: str
    total: int
    sources: list[ProjectSourceSummaryResponse]


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
    _, project_count = await db.list_projects_by_user(
        str(current_user["id"]), skip=0, limit=1
    )
    if project_count >= get_settings().max_projects_per_user:
        raise HTTPException(status_code=429, detail="project quota exceeded")
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
            "organization_id": current_user.get("active_organization_id"),
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
        status="pending",
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
                status=normalize_project_status(p.get("status"))[0],
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
    if not project_access_allowed(project, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    public_project = dict(project)
    public_status, current_phase = normalize_project_status(project.get("status"))
    public_project["status"] = public_status
    public_project["current_phase"] = current_phase
    return public_project


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

    if not project_access_allowed(project, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    from ..services.project_cleanup import delete_project_data

    await delete_project_data(project_id, db)

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

    if not project_access_allowed(project, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    execution = await db.get_latest_agent_execution(project_id)
    raw_project_status = str(project.get("status") or "created")
    normalized_project_status, current_phase = normalize_project_status(
        raw_project_status
    )
    execution_status = str(execution.get("status") or "") if execution else ""
    project_status = {
        "pending": "running",
        "running": "running",
        "succeeded": "completed",
        "failed": "failed",
        "interrupted": "interrupted",
        "cancelled": "interrupted",
    }.get(execution_status)
    if project_status is None:
        project_status = normalized_project_status
    if execution_status == "pending" and current_phase is None:
        current_phase = "supervisor"
    progress = None
    if execution:
        progress = {
            "execution_id": str(execution["id"]),
            "status": project_status,
            "duration_ms": execution.get("duration_ms"),
            "quality_score": execution.get("quality_score"),
        }

    return PipelineStatusResponse(
        project_id=project_id,
        execution_id=str(execution["id"]) if execution else None,
        status=project_status,
        current_phase=current_phase,
        current_node=current_phase,
        progress=progress,
        error_message=execution.get("error_message") if execution else None,
    )


@router.get("/projects/{project_id}/progress")
async def get_project_progress(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, Any]:
    """Rebuild canonical Agent phase history from persisted decisions."""
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project_access_allowed(project, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    execution = await db.get_latest_agent_execution(project_id)
    if not execution:
        return {"nodes": []}

    async with db.session() as session:
        result = await session.execute(
            text("""
                SELECT decision, reason, created_at
                FROM agent_decisions
                WHERE execution_id = :execution_id
                ORDER BY created_at ASC, id ASC
            """),
            {"execution_id": execution["id"]},
        )
        decisions = [dict(row._mapping) for row in result.fetchall()]

    allowed_phases = {
        "supervisor",
        "research",
        "analysis",
        "writing",
        "peer_review",
        "finalize",
    }
    phase_events = [
        decision
        for decision in decisions
        if str(decision.get("decision") or "") in allowed_phases
    ]
    if phase_events:
        phase_events.insert(
            0,
            {
                "decision": "supervisor",
                "reason": "execution accepted",
                "created_at": phase_events[0].get("created_at"),
            },
        )

    execution_status = str(execution.get("status") or "")
    failed_phase = ""
    if execution_status == "failed":
        for decision in reversed(phase_events):
            reason = str(decision.get("reason") or "")
            match = re.match(
                r"(research|analysis|writing|peer_review) exhausted", reason
            )
            if match:
                failed_phase = match.group(1)
                break

    latest_by_phase: dict[str, dict[str, Any]] = {}
    phase_order: list[str] = []
    for event in phase_events:
        phase = str(event["decision"])
        if phase not in latest_by_phase:
            phase_order.append(phase)
        latest_by_phase[phase] = event

    nodes: list[dict[str, Any]] = []
    for index, phase in enumerate(phase_order):
        event = latest_by_phase[phase]
        started_at = event.get("created_at")
        next_started = (
            latest_by_phase[phase_order[index + 1]].get("created_at")
            if index + 1 < len(phase_order)
            else None
        )
        if phase == failed_phase:
            status = "failed"
        elif index + 1 < len(phase_order) or execution_status == "succeeded":
            status = "completed"
        elif execution_status in {"failed", "interrupted", "cancelled"}:
            status = "failed" if execution_status == "failed" else "interrupted"
        else:
            status = "running"
        elapsed_ms = None
        if started_at is not None and next_started is not None:
            elapsed_ms = max(0, int((next_started - started_at).total_seconds() * 1000))
        nodes.append(
            {
                "node_name": phase,
                "status": status,
                "started_at": started_at.isoformat() if started_at else None,
                "finished_at": next_started.isoformat() if next_started else None,
                "elapsed_ms": elapsed_ms,
                "error_message": (
                    execution.get("error_message") if status == "failed" else None
                ),
            }
        )
    return {"execution_id": str(execution["id"]), "nodes": nodes}


@router.get(
    "/projects/{project_id}/sources",
    response_model=ProjectSourcesResponse,
)
async def get_project_sources(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, Any]:
    """Return project-scoped paper provenance grouped by academic source."""

    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project_access_allowed(project, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    papers = await db.get_project_papers(project_id, limit=500)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for paper in papers:
        source = str(paper.get("source") or "unknown").strip().lower()
        grouped.setdefault(source, []).append(
            {
                "id": str(paper.get("id") or ""),
                "title": str(paper.get("title") or "Untitled"),
                "authors": paper.get("authors") or [],
                "year": paper.get("year") or paper.get("publication_date"),
                "journal": paper.get("journal"),
                "doi": paper.get("doi"),
                "url": paper.get("url"),
                "citation_count": int(paper.get("citation_count") or 0),
            }
        )

    return {
        "project_id": project_id,
        "total": len(papers),
        "sources": [
            {
                "source": source,
                "count": len(source_papers),
                "papers": source_papers[:20],
            }
            for source, source_papers in sorted(grouped.items())
        ],
    }


# =============================================================================
# Pipeline 路由
# =============================================================================


async def _get_authorized_pipeline_project(
    project_id: str,
    current_user: dict[str, Any],
    db: DatabaseService,
) -> dict[str, Any]:
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project_access_allowed(project, current_user):
        raise HTTPException(status_code=403, detail="Access denied")
    return project


def _agent_targets(project: dict[str, Any]) -> tuple[int, int]:
    return resolve_agent_targets(project.get("config"))


async def _schedule_pipeline_agent(
    *,
    project: dict[str, Any],
    db: DatabaseService,
    resume: bool,
) -> str:
    from .sse import get_sse_manager

    target_papers, target_words = _agent_targets(project)
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
    except AgentQueueFullError as error:
        raise HTTPException(status_code=429, detail=str(error)) from error
    except AgentRuntimeUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/pipeline/{project_id}/start")
async def start_pipeline(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, str]:
    """启动唯一的持久化 Agent 流程（兼容旧 Pipeline API）。"""
    project = await _get_authorized_pipeline_project(project_id, current_user, db)
    logger.info("Starting agent pipeline", project_id=project_id)
    execution_id = await _schedule_pipeline_agent(
        project=project,
        db=db,
        resume=False,
    )
    return {
        "message": "Agent started",
        "project_id": project_id,
        "execution_id": execution_id,
    }


@router.post("/pipeline/{project_id}/pause")
async def pause_pipeline(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, str]:
    """暂停 Agent，并等待执行记录写为 interrupted。"""
    await _get_authorized_pipeline_project(project_id, current_user, db)
    logger.info("Pausing agent", project_id=project_id)
    try:
        execution_id = await get_agent_run_manager().cancel(project_id)
    except AgentNotRunningError as error:
        raise HTTPException(status_code=409, detail="Agent not running") from error
    except AgentCancellationTimeoutError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    if not execution_id:
        execution = await db.get_latest_agent_execution(project_id)
        if not execution:
            raise HTTPException(status_code=409, detail="Agent execution not found")
        execution_id = str(execution["id"])
    return {
        "message": "Agent paused",
        "project_id": project_id,
        "execution_id": execution_id,
    }


@router.post("/pipeline/{project_id}/resume")
async def resume_pipeline(
    project_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
) -> dict[str, str]:
    """按 checkpoint 状态恢复、协调终态或创建可追踪的新执行。"""
    project = await _get_authorized_pipeline_project(project_id, current_user, db)
    logger.info("Resuming agent from checkpoint", project_id=project_id)
    execution_id = await _schedule_pipeline_agent(
        project=project,
        db=db,
        resume=True,
    )
    return {
        "message": "Pipeline resume or retry accepted",
        "project_id": project_id,
        "execution_id": execution_id,
    }


# =============================================================================
# 大纲读取路由
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

    if not project_access_allowed(project, current_user):
        raise HTTPException(status_code=403, detail="Access denied")

    outline = await db.get_outline_by_project_id(project_id)

    return {
        "project_id": project_id,
        "outline": outline,
        "status": outline.get("status", "pending") if outline else "pending",
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

    if not project_access_allowed(project, current_user):
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

    evidence_cards = await db.get_project_evidence_cards(project_id)

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

    raw_status = str(project.get("status") or "created")
    public_status, _current_phase = normalize_project_status(raw_status)
    return {
        "project_id": project_id,
        "outline": outline,
        "sections": sections,
        "evidence_cards": evidence_cards,
        "references": references,
        "final_review": final_review,
        "abstract": abstract,
        "status": public_status,
    }
