"""
重排序节点 - 使用 Rerank 模型对论文进行重排序

使用 Provider Pool 自动负载均衡多个 Rerank 端点。
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

        reranked.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
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
    core_count = config.get("core_reference_count", 80)
    auxiliary_count = config.get("auxiliary_reference_count", 160)

    db = get_database()
    papers = await db.get_papers_by_ids(state.paper_ids)

    if not papers:
        logger.warning("No papers to rerank")
        return {
            "core_paper_ids": [],
            "auxiliary_paper_ids": [],
            "status": "reranked",
        }

    try:
        # 重排序（通过 Provider Pool 自动负载均衡）
        reranked_papers = await rerank_papers(state.query, papers)

        # 分为核心和辅助参考
        core_paper_ids = [p.get("id") for p in reranked_papers[:core_count]]
        auxiliary_paper_ids = [p.get("id") for p in reranked_papers[core_count:core_count + auxiliary_count]]

        logger.info(
            "Reranking completed",
            total_papers=len(reranked_papers),
            core_count=len(core_paper_ids),
            auxiliary_count=len(auxiliary_paper_ids),
        )

        await send_progress(
            state.project_id, "rerank",
            f"重排序完成，核心 {len(core_paper_ids)} 篇，辅助 {len(auxiliary_paper_ids)} 篇",
        )

        result = {
            "core_paper_ids": core_paper_ids,
            "auxiliary_paper_ids": auxiliary_paper_ids,
            "status": "reranked",
        }

        if tracker:
            await tracker.end_node("rerank", "succeeded", output_summary={
                "core_count": len(core_paper_ids),
                "auxiliary_count": len(auxiliary_paper_ids),
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
