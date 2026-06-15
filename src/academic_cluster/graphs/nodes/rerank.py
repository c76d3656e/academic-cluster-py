"""
重排序节点 - 使用 Rerank 模型对论文进行重排序

使用 Provider Pool 自动负载均衡多个 Rerank 端点。
对齐 Rust 版 quality scoring: 0.40*relevance + 0.20*venue + 0.15*recency + 0.15*meta + 0.10*rel2
"""

import asyncio
import traceback

import httpx
import structlog

from ...services.database import get_database
from ...services.observability import get_current_tracker
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()

# 质量评分公式权重（对齐 Rust 版 score_and_tier_papers）
_QUALITY_WEIGHT_RELEVANCE = 0.40
_QUALITY_WEIGHT_VENUE = 0.20
_QUALITY_WEIGHT_RECENCY = 0.15
_QUALITY_WEIGHT_META = 0.15
_QUALITY_WEIGHT_REL2 = 0.10
_CURRENT_YEAR = 2026  # 用于 recency 计算


def _metadata_completeness(paper: dict) -> int:
    """
    计算论文元数据完整度（对齐 Rust 版 metadata_completeness）。

    满分 4 分：
    - has_title: 1
    - has_useful_abstract: 1 (>120 chars)
    - has_publication_name: 1
    - has_doi: 1
    """
    score = 0
    if paper.get("title"):
        score += 1
    abstract = paper.get("abstract", "")
    if abstract and len(abstract) > 120:
        score += 1
    if paper.get("journal") or paper.get("venue"):
        score += 1
    if paper.get("doi"):
        score += 1
    return score


def _compute_quality_score(paper: dict) -> float:
    """
    计算论文质量分数（对齐 Rust 版 score_and_tier_papers）。

    公式: 0.40*relevance + 0.20*venue + 0.15*recency + 0.15*meta + 0.10*rel2
    """
    relevance = max(0.0, min(1.0, paper.get("rerank_score", 0.0)))

    # venue_score: 目前未实现 JCR 数据，hardcode 0.0（与 Rust 版一致）
    venue_score = 0.0

    # recency: (year - 2015) / (2026 - 2015), clamped [0, 1]
    year = paper.get("year")
    if year:
        try:
            year = int(year)
            recency = max(0.0, min(1.0, (year - 2015) / (_CURRENT_YEAR - 2015)))
        except (ValueError, TypeError):
            recency = 0.0
    else:
        recency = 0.0

    # meta_score: metadata_completeness / 4.0
    meta_score = _metadata_completeness(paper) / 4.0

    # rel2: boosted relevance, capped at 1.0
    rel2 = min(1.0, relevance * 2.0)

    quality = (
        _QUALITY_WEIGHT_RELEVANCE * relevance
        + _QUALITY_WEIGHT_VENUE * venue_score
        + _QUALITY_WEIGHT_RECENCY * recency
        + _QUALITY_WEIGHT_META * meta_score
        + _QUALITY_WEIGHT_REL2 * rel2
    )

    return round(quality, 4)


def _quality_tier(score: float) -> str:
    """质量等级（对齐 Rust 版 tier 划分）"""
    if score >= 0.40:
        return "A"
    elif score >= 0.16:
        return "B"
    elif score >= 0.06:
        return "C"
    return "noise"


async def rerank_papers(query: str, papers: list[dict], timeout: float = 120.0) -> list[dict]:
    """
    使用 Rerank 模型对论文进行重排序

    通过 Provider Pool 自动选择可用的 Rerank 端点。
    超时保护：整体调用超过 timeout 秒则抛出 TimeoutError。
    """
    from ...services.provider_pool import get_rerank_pool

    pool = get_rerank_pool()

    # 构建文档列表
    documents = []
    for paper in papers:
        title = paper.get("title", "")
        abstract = paper.get("abstract", "")
        documents.append(f"{title} {abstract}".strip())

    async def _do_rerank(provider) -> list[dict]:
        base = provider.api_url.rstrip("/")
        if not base.endswith("/v1"):
            url = f"{base}/v1/rerank"
        else:
            url = f"{base}/rerank"
        headers = {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": provider.model,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers, timeout=60)
            response.raise_for_status()
            data = response.json()

        # 整理结果
        results = data.get("results", [])
        reranked = []
        for result in results:
            idx = result.get("index", 0)
            score = float(result.get("relevance_score", 0.0))
            if idx < len(papers):
                paper = papers[idx].copy()
                paper["rerank_score"] = score
                reranked.append(paper)

        # 应用质量评分（对齐 Rust 版 score_and_tier_papers）
        for paper in reranked:
            paper["quality_score"] = _compute_quality_score(paper)
            paper["quality_tier"] = _quality_tier(paper["quality_score"])

        # 按质量分数排序
        reranked.sort(key=lambda x: x.get("quality_score", 0), reverse=True)
        return reranked

    return await asyncio.wait_for(
        pool.execute(_do_rerank),
        timeout=timeout,
    )


async def rerank_node(state: PipelineState) -> dict:
    """
    重排序论文

    使用 Rerank 模型对论文进行重排序：
    - 计算查询与论文的相关性分数
    - 按分数排序
    - 分为核心参考（top 80）和辅助参考（next 160）
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("rerank", "compute", index=2)

    logger.info("Starting reranking", paper_count=len(state.paper_ids))

    await send_progress(
        state.project_id, "rerank",
        f"正在重排序 {len(state.paper_ids)} 篇论文...",
    )

    config = state.config or {}
    max_papers = config.get("rerank.max_papers", 500)
    db = get_database()
    papers = await db.get_papers_by_ids(state.paper_ids)

    if not papers:
        logger.warning("No papers to rerank")
        return {
            "reranked_paper_ids": [],
            "status": "reranked",
        }

    try:
        # 重排序（通过 Provider Pool 自动负载均衡）
        import time as _time
        _rerank_start = _time.monotonic()
        reranked_papers = await rerank_papers(state.query, papers)
        _rerank_elapsed = int((_time.monotonic() - _rerank_start) * 1000)

        # 记录 rerank 调用到 tracker 和 DB
        if tracker and tracker.run_id:
            try:
                from ...api.admin.providers import get_provider_pricing
                from ...services.provider_pool import get_rerank_pool

                db = get_database()
                rerank_pool = get_rerank_pool()
                # 获取当前使用的 provider 名称
                provider_name = rerank_pool._providers[0].name if rerank_pool._providers else "unknown"
                rerank_model = rerank_pool._providers[0].model if rerank_pool._providers else "unknown"

                # rerank 通常按文档数计费，这里用调用次数近似
                prompt_tokens = len(papers)  # 每篇论文算 1 token
                completion_tokens = 0

                # 计算 cost（rerank 通常按调用次数计费，这里按 token 近似）
                input_price, output_price = await get_provider_pricing(db, provider_name, rerank_model)
                cost = 0.0
                if input_price:
                    cost = (prompt_tokens * input_price) / 1_000_000

                await tracker.token_tracker.record(
                    node_name="rerank",
                    provider_name=provider_name,
                    model_name=rerank_model,
                    call_type="rerank",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                    cost=cost,
                    latency_ms=_rerank_elapsed,
                )

                exec_id = tracker._node_ids.get("rerank")
                if not exec_id:
                    exec_id = await db.create_node_execution(
                        tracker.run_id,
                        "rerank",
                        "rerank",
                    )
                    tracker._node_ids["rerank"] = exec_id
                call_id = await db.create_llm_call(
                    pipeline_run_id=tracker.run_id,
                    node_execution_id=exec_id,
                    project_id=tracker.project_id,
                    node_name="rerank",
                    call_type="rerank",
                    provider_name=provider_name,
                    model_name=rerank_model,
                    requested_model=rerank_model,
                    upstream_model=rerank_model,
                    latency_ms=_rerank_elapsed,
                    request_metadata={
                        "node_name": "rerank",
                        "provider_name": provider_name,
                    },
                )
                await db.finish_llm_call(
                    call_id=call_id,
                    status="success",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                    cost=cost,
                    latency_ms=_rerank_elapsed,
                )
            except Exception:
                pass  # 追踪失败不影响主流程

        # 取 top max_papers（默认 500）作为最终 reranked 结果
        reranked_papers = reranked_papers[:max_papers]
        reranked_paper_ids = [p.get("id") for p in reranked_papers]

        logger.info(
            "Reranking completed",
            total_input=len(papers),
            reranked_count=len(reranked_paper_ids),
        )

        await send_progress(
            state.project_id, "rerank",
            f"重排序完成，筛选出 {len(reranked_paper_ids)} 篇高质量论文",
        )

        result = {
            "reranked_paper_ids": reranked_paper_ids,
            "status": "reranked",
        }

        if tracker:
            await tracker.end_node("rerank", "succeeded", output_summary={
                "reranked_count": len(reranked_paper_ids),
            })
        return result

    except asyncio.TimeoutError:
        error_msg = f"Reranking timed out after 120s for {len(papers)} papers"
        logger.error(
            "Reranking timed out",
            project_id=state.project_id,
            paper_count=len(papers),
            query=state.query,
            timeout_seconds=120,
        )
        if tracker:
            await tracker.end_node("rerank", "failed",
                                   error_message=error_msg)
        raise TimeoutError(error_msg)
    except Exception as e:
        logger.error(
            "Reranking failed",
            project_id=state.project_id,
            paper_count=len(papers),
            query=state.query,
            error=str(e),
            error_type=type(e).__name__,
            traceback=traceback.format_exc(),
        )
        if tracker:
            await tracker.end_node("rerank", "failed",
                                   error_message=str(e),
                                   error_traceback=traceback.format_exc())
        raise
