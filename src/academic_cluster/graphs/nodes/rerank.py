"""
重排序节点 - 使用 Rerank 模型对论文进行重排序
"""

import httpx
import structlog

from ...config import get_settings
from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def rerank_papers(query: str, papers: list[dict]) -> list[dict]:
    """
    使用 Rerank 模型对论文进行重排序

    调用 Rerank API（如 BAAI/bge-reranker-v2-m3）
    """
    settings = get_settings()

    url = f"{settings.rerank.api_url}/rerank"
    headers = {
        "Authorization": f"Bearer {settings.rerank.api_key}",
        "Content-Type": "application/json",
    }

    # 构建文档列表
    documents = []
    for paper in papers:
        title = paper.get("title", "")
        abstract = paper.get("abstract", "")
        documents.append(f"{title} {abstract}".strip())

    payload = {
        "model": settings.rerank.model,
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
    reranked_papers = []

    for result in results:
        idx = result.get("index", 0)
        score = result.get("relevance_score", 0.0)
        if idx < len(papers):
            paper = papers[idx].copy()
            paper["rerank_score"] = score
            reranked_papers.append(paper)

    # 按分数排序
    reranked_papers.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)

    return reranked_papers


async def rerank_node(state: PipelineState) -> dict:
    """
    重排序论文

    使用 Rerank 模型对论文进行重排序：
    - 计算查询与论文的相关性分数
    - 按分数排序
    - 分为核心参考（top 80）和辅助参考（next 160）
    """
    logger.info("Starting reranking", paper_count=len(state.paper_ids))

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
        # 重排序
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

        return {
            "core_paper_ids": core_paper_ids,
            "auxiliary_paper_ids": auxiliary_paper_ids,
            "status": "reranked",
        }

    except Exception as e:
        logger.error("Reranking failed", error=str(e))
        # 回退：按引用数量排序
        papers.sort(key=lambda x: x.get("citation_count", 0), reverse=True)
        core_paper_ids = [p.get("id") for p in papers[:core_count]]
        auxiliary_paper_ids = [p.get("id") for p in papers[core_count:core_count + auxiliary_count]]

        return {
            "core_paper_ids": core_paper_ids,
            "auxiliary_paper_ids": auxiliary_paper_ids,
            "status": "reranked",
            "errors": [f"Reranking failed, fallback to citation count: {str(e)}"],
        }
