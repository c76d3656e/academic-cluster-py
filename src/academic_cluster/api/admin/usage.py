"""
管理后台 - 用量分析

提供 Token/成本趋势、按 Provider 分组统计、最近 LLM 调用记录等端点。
"""

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from ..dependencies import require_admin
from ...services.database import DatabaseService, get_database

logger = structlog.get_logger()

router = APIRouter(tags=["admin-usage"])


# =============================================================================
# 响应模型
# =============================================================================

class UsageTrendItem(BaseModel):
    """用量趋势项"""
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


class ProviderUsageItem(BaseModel):
    """Provider 用量统计"""
    provider_name: str | None = None
    model_name: str | None = None
    call_type: str | None = None
    call_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    avg_latency_ms: float | None = None


class RecentCallItem(BaseModel):
    """最近 LLM 调用记录"""
    id: str
    pipeline_run_id: str | None = None
    provider_name: str | None = None
    model_name: str | None = None
    call_type: str | None = None
    status: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None
    latency_ms: float | None = None
    created_at: str | None = None
    # input/output 拆分 (prompt_tokens = input, completion_tokens = output)


# =============================================================================
# 端点
# =============================================================================

@router.get("/trend", response_model=list[UsageTrendItem])
async def get_usage_trend(
    days: int = 30,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """获取每日 Token/成本趋势"""
    days = max(1, min(days, 365))

    async with db.session() as session:
        result = await session.execute(
            text("""
                SELECT
                    DATE(created_at) AS date,
                    COUNT(*) AS call_count,
                    COALESCE(SUM(total_tokens), 0) AS total_tokens,
                    COALESCE(SUM(cost), 0) AS total_cost,
                    COALESCE(SUM(CASE WHEN call_type = 'llm' THEN total_tokens ELSE 0 END), 0) AS llm_tokens,
                    COALESCE(SUM(CASE WHEN call_type = 'embedding' THEN total_tokens ELSE 0 END), 0) AS embedding_tokens,
                    COALESCE(SUM(CASE WHEN call_type = 'rerank' THEN total_tokens ELSE 0 END), 0) AS rerank_tokens,
                    COALESCE(SUM(CASE WHEN call_type = 'llm' THEN cost ELSE 0 END), 0) AS llm_cost,
                    COALESCE(SUM(CASE WHEN call_type = 'embedding' THEN cost ELSE 0 END), 0) AS embedding_cost,
                    COALESCE(SUM(CASE WHEN call_type = 'rerank' THEN cost ELSE 0 END), 0) AS rerank_cost,
                    COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                    COALESCE(SUM(completion_tokens), 0) AS completion_tokens
                FROM llm_calls
                WHERE created_at >= NOW() - INTERVAL '1 day' * :days
                GROUP BY DATE(created_at)
                ORDER BY date DESC
            """),
            {"days": days},
        )
        rows = result.fetchall()

    return [
        UsageTrendItem(
            date=str(row[0]),
            call_count=row[1],
            total_tokens=row[2],
            total_cost=float(row[3]),
            llm_tokens=row[4],
            embedding_tokens=row[5],
            rerank_tokens=row[6],
            llm_cost=float(row[7]),
            embedding_cost=float(row[8]),
            rerank_cost=float(row[9]),
            prompt_tokens=row[10],
            completion_tokens=row[11],
        )
        for row in rows
    ]


@router.get("/by-provider", response_model=list[ProviderUsageItem])
async def get_usage_by_provider(
    days: int = 30,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """获取按 Provider/模型分组的用量统计"""
    days = max(1, min(days, 365))

    summary = await db.get_provider_usage_summary(days=days)

    return [
        ProviderUsageItem(
            provider_name=item.get("provider_name"),
            model_name=item.get("model_name"),
            call_type=item.get("call_type"),
            call_count=item.get("call_count", 0),
            success_count=item.get("success_count", 0),
            error_count=item.get("error_count", 0),
            total_prompt_tokens=item.get("total_prompt_tokens", 0),
            total_completion_tokens=item.get("total_completion_tokens", 0),
            total_tokens=item.get("total_tokens", 0),
            total_cost=float(item.get("total_cost", 0)),
            avg_latency_ms=float(item["avg_latency_ms"]) if item.get("avg_latency_ms") else None,
        )
        for item in summary
    ]


@router.get("/recent-calls", response_model=list[RecentCallItem])
async def get_recent_calls(
    limit: int = 50,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """获取最近的 LLM 调用记录"""
    limit = max(1, min(limit, 200))

    async with db.session() as session:
        result = await session.execute(
            text("""
                SELECT id, pipeline_run_id, provider_name, model_name,
                       call_type, status, prompt_tokens, completion_tokens,
                       total_tokens, cost, latency_ms, created_at
                FROM llm_calls
                ORDER BY created_at DESC
                LIMIT :limit
            """),
            {"limit": limit},
        )
        rows = result.fetchall()

    return [
        RecentCallItem(
            id=str(row[0]),
            pipeline_run_id=str(row[1]) if row[1] else None,
            provider_name=row[2],
            model_name=row[3],
            call_type=row[4],
            status=row[5],
            prompt_tokens=row[6],
            completion_tokens=row[7],
            total_tokens=row[8],
            cost=float(row[9]) if row[9] is not None else None,
            latency_ms=float(row[10]) if row[10] is not None else None,
            created_at=str(row[11]) if row[11] else None,
        )
        for row in rows
    ]
