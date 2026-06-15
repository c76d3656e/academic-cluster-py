"""
Console 用量路由

提供用户 LLM 用量趋势和调用记录查询。
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from ..dependencies import get_current_user
from ...services.database import DatabaseService, get_database

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# 响应模型
# =============================================================================

class DailyTrendItem(BaseModel):
    """每日用量趋势"""
    date: str
    call_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    # 按 call_type 分组的 token 细分
    llm_tokens: int = 0
    embedding_tokens: int = 0
    rerank_tokens: int = 0
    llm_cost: float = 0.0
    embedding_cost: float = 0.0
    rerank_cost: float = 0.0
    # input/output 拆分
    prompt_tokens: int = 0
    completion_tokens: int = 0


class UsageTrendResponse(BaseModel):
    """用量趋势响应"""
    days: int
    trend: list[DailyTrendItem]


class LLMCallRecord(BaseModel):
    """LLM 调用记录"""
    id: str
    pipeline_run_id: str | None = None
    provider_name: str
    model_name: str
    call_type: str
    status: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    created_at: datetime | None = None
    project_id: str | None = None


class LLMCallListResponse(BaseModel):
    """LLM 调用记录列表响应"""
    calls: list[LLMCallRecord]
    total: int


# =============================================================================
# 端点
# =============================================================================

@router.get("/usage/trend", response_model=UsageTrendResponse)
async def get_usage_trend(
    days: int = Query(7, ge=1, le=90),
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
):
    """获取用户每日用量趋势"""
    user_id = current_user["id"]

    async with db.session() as session:
        result = await session.execute(
            text("""
                SELECT
                    DATE(lc.created_at) AS date,
                    COUNT(*) AS call_count,
                    COALESCE(SUM(lc.total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(lc.cost), 0) AS total_cost,
                    COALESCE(SUM(CASE WHEN lc.call_type = 'llm' THEN lc.total_tokens ELSE 0 END), 0) AS llm_tokens,
                    COALESCE(SUM(CASE WHEN lc.call_type = 'embedding' THEN lc.total_tokens ELSE 0 END), 0) AS embedding_tokens,
                    COALESCE(SUM(CASE WHEN lc.call_type = 'rerank' THEN lc.total_tokens ELSE 0 END), 0) AS rerank_tokens,
                    COALESCE(SUM(CASE WHEN lc.call_type = 'llm' THEN lc.cost ELSE 0 END), 0) AS llm_cost,
                    COALESCE(SUM(CASE WHEN lc.call_type = 'embedding' THEN lc.cost ELSE 0 END), 0) AS embedding_cost,
                    COALESCE(SUM(CASE WHEN lc.call_type = 'rerank' THEN lc.cost ELSE 0 END), 0) AS rerank_cost,
                    COALESCE(SUM(lc.prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(lc.completion_tokens), 0) AS completion_tokens
                FROM llm_calls lc
                JOIN pipeline_runs pr ON lc.pipeline_run_id = pr.id
                WHERE pr.project_id IN (
                    SELECT id FROM projects WHERE user_id = :user_id
                )
                AND lc.created_at >= NOW() - (:days * INTERVAL '1 day')
                GROUP BY DATE(lc.created_at)
                ORDER BY date
            """),
            {"user_id": user_id, "days": days},
        )
        rows = result.fetchall()

    trend = [
        DailyTrendItem(
            date=str(row[0]),
            call_count=int(row[1]),
            total_tokens=int(row[2]),
            total_cost=float(row[3]),
            llm_tokens=int(row[4]),
            embedding_tokens=int(row[5]),
            rerank_tokens=int(row[6]),
            llm_cost=float(row[7]),
            embedding_cost=float(row[8]),
            rerank_cost=float(row[9]),
            prompt_tokens=int(row[10]),
            completion_tokens=int(row[11]),
        )
        for row in rows
    ]

    return UsageTrendResponse(days=days, trend=trend)


@router.get("/usage/calls", response_model=LLMCallListResponse)
async def get_usage_calls(
    limit: int = Query(50, ge=1, le=200),
    project_id: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
):
    """获取用户的 LLM 调用记录"""
    user_id = current_user["id"]

    # 构建查询条件
    params: dict = {"user_id": user_id, "limit": limit}
    project_filter = ""
    if project_id:
        project_filter = "AND pr.project_id = :project_id"
        params["project_id"] = project_id

    async with db.session() as session:
        # 总数
        count_result = await session.execute(
            text(f"""
                SELECT COUNT(*)
                FROM llm_calls lc
                JOIN pipeline_runs pr ON lc.pipeline_run_id = pr.id
                WHERE pr.project_id IN (
                    SELECT id FROM projects WHERE user_id = :user_id
                )
                {project_filter}
            """),
            params,
        )
        total = count_result.scalar() or 0

        # 记录列表
        result = await session.execute(
            text(f"""
                SELECT
                    lc.id,
                    lc.pipeline_run_id,
                    lc.provider_name,
                    lc.model_name,
                    lc.call_type,
                    lc.status,
                    lc.prompt_tokens,
                    lc.completion_tokens,
                    lc.total_tokens,
                    lc.cost,
                    lc.latency_ms,
                    lc.created_at,
                    pr.project_id
                FROM llm_calls lc
                JOIN pipeline_runs pr ON lc.pipeline_run_id = pr.id
                WHERE pr.project_id IN (
                    SELECT id FROM projects WHERE user_id = :user_id
                )
                {project_filter}
                ORDER BY lc.created_at DESC
                LIMIT :limit
            """),
            params,
        )
        rows = result.fetchall()

    calls = [
        LLMCallRecord(
            id=str(row[0]),
            pipeline_run_id=str(row[1]) if row[1] else None,
            provider_name=row[2] or "",
            model_name=row[3] or "",
            call_type=row[4] or "",
            status=row[5] or "success",
            prompt_tokens=int(row[6]) if row[6] else 0,
            completion_tokens=int(row[7]) if row[7] else 0,
            total_tokens=int(row[8]) if row[8] else 0,
            cost=float(row[9]) if row[9] else 0.0,
            latency_ms=int(row[10]) if row[10] else 0,
            created_at=row[11],
            project_id=str(row[12]) if row[12] else None,
        )
        for row in rows
    ]

    return LLMCallListResponse(calls=calls, total=total)
