"""
Console 用量路由

提供用户 LLM 用量趋势和调用记录查询。
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import text

from ...services.database import DatabaseService, get_database
from ..dependencies import get_current_user

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
    project_id: str | None = None
    project_name: str | None = None
    node_execution_id: str | None = None
    node_name: str | None = None
    provider_name: str
    model_name: str
    requested_model: str | None = None
    upstream_model: str | None = None
    call_type: str
    status: str
    run_status: str | None = None
    error_message: str | None = None
    http_status_code: int | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0
    input_price_per_m: float | None = None
    output_price_per_m: float | None = None
    latency_ms: int = 0
    input_preview: str | None = None
    output_preview: str | None = None
    request_metadata: dict | None = None
    created_at: datetime | None = None


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
    granularity: str = Query("day", pattern="^(day|hour)$"),
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
):
    """获取用户用量趋势，支持 day/hour 粒度"""
    user_id = current_user["id"]

    time_group = "DATE(lc.created_at)" if granularity == "day" else "date_trunc('hour', lc.created_at)"
    run_time_group = "DATE(pr.created_at)" if granularity == "day" else "date_trunc('hour', pr.created_at)"
    time_filter = "lc.created_at >= NOW() - (:days * INTERVAL '1 day')"
    run_time_filter = "pr.created_at >= NOW() - (:days * INTERVAL '1 day')"

    async with db.session() as session:
        result = await session.execute(
            text(f"""
                WITH call_daily AS (
                    SELECT
                        {time_group} AS date,
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
                    LEFT JOIN pipeline_runs pr ON lc.pipeline_run_id = pr.id
                    LEFT JOIN projects p ON COALESCE(lc.project_id, pr.project_id) = p.id
                    WHERE (p.user_id = :user_id OR lc.project_id IN (SELECT id FROM projects WHERE user_id = :user_id))
                    AND {time_filter}
                    GROUP BY {time_group}
                ),
                run_daily AS (
                    SELECT
                        {run_time_group} AS date,
                        COALESCE(SUM(pr.total_llm_calls), 0) AS call_count,
                        COALESCE(SUM(pr.total_tokens), 0) AS total_tokens,
                        COALESCE(SUM(pr.total_cost), 0) AS total_cost,
                        COALESCE(SUM(pr.total_tokens), 0) AS llm_tokens,
                        0 AS embedding_tokens,
                        0 AS rerank_tokens,
                        COALESCE(SUM(pr.total_cost), 0) AS llm_cost,
                        0 AS embedding_cost,
                        0 AS rerank_cost,
                        COALESCE(SUM(pr.total_prompt_tokens), 0) AS prompt_tokens,
                        COALESCE(SUM(pr.total_completion_tokens), 0) AS completion_tokens
                    FROM pipeline_runs pr
                    WHERE pr.project_id IN (
                        SELECT id FROM projects WHERE user_id = :user_id
                    )
                    AND {run_time_filter}
                    AND pr.total_llm_calls > 0
                    AND NOT EXISTS (
                        SELECT 1 FROM llm_calls lc WHERE lc.pipeline_run_id = pr.id
                    )
                    GROUP BY {run_time_group}
                ),
                usage_daily AS (
                    SELECT * FROM call_daily
                    UNION ALL
                    SELECT * FROM run_daily
                )
                SELECT
                    date,
                    COALESCE(SUM(call_count), 0) AS call_count,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(total_cost), 0) AS total_cost,
                    COALESCE(SUM(llm_tokens), 0) AS llm_tokens,
                    COALESCE(SUM(embedding_tokens), 0) AS embedding_tokens,
                    COALESCE(SUM(rerank_tokens), 0) AS rerank_tokens,
                    COALESCE(SUM(llm_cost), 0) AS llm_cost,
                    COALESCE(SUM(embedding_cost), 0) AS embedding_cost,
                    COALESCE(SUM(rerank_cost), 0) AS rerank_cost,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens
                FROM usage_daily
                GROUP BY date
                ORDER BY date
            """),  # nosec B608
            {"user_id": user_id, "days": days},
        )
        rows = result.fetchall()

    if granularity == "hour":
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
    else:
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
    node_name: str | None = Query(None),
    status: str | None = Query(None),
    call_type: str | None = Query(None),
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
):
    """获取用户的 LLM 调用记录"""
    user_id = current_user["id"]

    # 构建查询条件
    is_admin = current_user.get("role") == "admin"
    owner_filter = (
        "TRUE"
        if is_admin
        else "(p.user_id = :user_id OR lc.project_id IN (SELECT id FROM projects WHERE user_id = :user_id))"
    )
    params: dict = {"user_id": user_id, "limit": limit}
    project_filter = ""
    if project_id:
        project_filter = "AND COALESCE(lc.project_id, pr.project_id) = :project_id"
        params["project_id"] = project_id
    node_filter = ""
    if node_name:
        node_filter = "AND COALESCE(lc.node_name, ne.node_name) = :node_name"
        params["node_name"] = node_name
    status_filter = ""
    if status:
        status_filter = "AND lc.status = :status"
        params["status"] = status
    call_type_filter = ""
    if call_type:
        call_type_filter = "AND lc.call_type = :call_type"
        params["call_type"] = call_type

    async with db.session() as session:
        # 总数
        count_result = await session.execute(
            text(f"""
                SELECT COUNT(*)
                FROM llm_calls lc
                LEFT JOIN pipeline_runs pr ON lc.pipeline_run_id = pr.id
                LEFT JOIN projects p ON COALESCE(lc.project_id, pr.project_id) = p.id
                LEFT JOIN node_executions ne ON lc.node_execution_id = ne.id
                WHERE {owner_filter}
                {project_filter}
                {node_filter}
                {status_filter}
                {call_type_filter}
            """),  # nosec B608
            params,
        )
        total = count_result.scalar() or 0

        # 记录列表
        result = await session.execute(
            text(f"""
                SELECT
                    lc.id,
                    lc.pipeline_run_id,
                    COALESCE(lc.project_id, pr.project_id) AS project_id,
                    p.name AS project_name,
                    lc.node_execution_id,
                    COALESCE(lc.node_name, ne.node_name) AS node_name,
                    lc.provider_name,
                    lc.model_name,
                    COALESCE(lc.requested_model, lc.model_name) AS requested_model,
                    COALESCE(lc.upstream_model, lc.model_name) AS upstream_model,
                    lc.call_type,
                    lc.status,
                    pr.status AS run_status,
                    lc.error_message,
                    lc.http_status_code,
                    lc.prompt_tokens,
                    lc.completion_tokens,
                    lc.total_tokens,
                    lc.cost,
                    lc.input_price_per_m,
                    lc.output_price_per_m,
                    lc.latency_ms,
                    lc.input_preview,
                    lc.output_preview,
                    lc.request_metadata,
                    lc.created_at
                FROM llm_calls lc
                LEFT JOIN pipeline_runs pr ON lc.pipeline_run_id = pr.id
                LEFT JOIN projects p ON COALESCE(lc.project_id, pr.project_id) = p.id
                LEFT JOIN node_executions ne ON lc.node_execution_id = ne.id
                WHERE {owner_filter}
                {project_filter}
                {node_filter}
                {status_filter}
                {call_type_filter}
                ORDER BY lc.created_at DESC
                LIMIT :limit
            """),  # nosec B608
            params,
        )
        rows = result.fetchall()

    calls = [
        LLMCallRecord(
            id=str(row[0]),
            pipeline_run_id=str(row[1]) if row[1] else None,
            project_id=str(row[2]) if row[2] else None,
            project_name=row[3],
            node_execution_id=str(row[4]) if row[4] else None,
            node_name=row[5],
            provider_name=row[6] or "",
            model_name=row[7] or "",
            requested_model=row[8],
            upstream_model=row[9],
            call_type=row[10] or "",
            status=row[11] or "success",
            run_status=row[12],
            error_message=row[13],
            http_status_code=int(row[14]) if row[14] else None,
            prompt_tokens=int(row[15]) if row[15] else 0,
            completion_tokens=int(row[16]) if row[16] else 0,
            total_tokens=int(row[17]) if row[17] else 0,
            cost=float(row[18]) if row[18] else 0.0,
            input_price_per_m=float(row[19]) if row[19] is not None else None,
            output_price_per_m=float(row[20]) if row[20] is not None else None,
            latency_ms=int(row[21]) if row[21] else 0,
            input_preview=row[22],
            output_preview=row[23],
            request_metadata=row[24],
            created_at=row[25],
        )
        for row in rows
    ]

    return LLMCallListResponse(calls=calls, total=total)
