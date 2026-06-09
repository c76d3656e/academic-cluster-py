"""
搜索节点 - 从多个学术数据源搜索论文
"""

import asyncio
import uuid

import structlog

from ...tools.academic_search import search_all_sources
from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def search_node(state: PipelineState) -> dict:
    """
    搜索学术论文

    使用多个数据源并行搜索：
    - Semantic Scholar
    - PubMed
    - arXiv
    - OpenAlex
    """
    logger.info("Starting paper search", query=state.query, project_id=state.project_id)

    # 从配置获取搜索参数
    config = state.config or {}
    limit_per_source = config.get("limit_per_source", 50)
    sources = config.get("sources", ["semantic_scholar", "arxiv"])

    # 并行搜索多个数据源
    papers = await search_all_sources(
        query=state.query,
        limit_per_source=limit_per_source,
        sources=sources,
    )

    # 去重（基于标题相似性）
    unique_papers = _deduplicate_papers(papers)

    # 保存到数据库并获取 ID
    db = get_database()
    paper_ids = []

    for paper in unique_papers:
        paper_id = paper.get("id", str(uuid.uuid4()))
        paper["id"] = paper_id

        try:
            await db.save_paper(paper)
            paper_ids.append(paper_id)
        except Exception as e:
            logger.warning("Failed to save paper", paper_id=paper_id, error=str(e))

    total_searched = len(papers)

    logger.info(
        "Search completed",
        total_searched=total_searched,
        unique_papers=len(unique_papers),
        papers_saved=len(paper_ids),
    )

    return {
        "paper_ids": paper_ids,
        "total_searched": total_searched,
        "status": "searched",
    }


def _deduplicate_papers(papers: list[dict]) -> list[dict]:
    """
    去除重复论文

    基于标题相似性去重
    """
    seen_titles = set()
    unique_papers = []

    for paper in papers:
        title = paper.get("title", "").lower().strip()
        if not title:
            continue

        # 简单的标题去重
        normalized_title = " ".join(title.split())
        if normalized_title not in seen_titles:
            seen_titles.add(normalized_title)
            unique_papers.append(paper)

    return unique_papers
