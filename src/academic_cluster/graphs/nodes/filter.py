"""
过滤节点 - 基于质量标准过滤论文
"""

import structlog

from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def filter_node(state: PipelineState) -> dict:
    """
    过滤论文

    基于以下标准过滤：
    - 最小引用数量
    - 发表年份
    - 有摘要
    """
    logger.info("Starting paper filtering", paper_count=len(state.paper_ids))

    config = state.config or {}
    min_citation_count = config.get("min_citation_count", 0)
    min_year = config.get("min_year", None)
    require_abstract = config.get("require_abstract", True)

    db = get_database()
    papers = await db.get_papers_by_ids(state.paper_ids)

    filtered_papers = []

    for paper in papers:
        # 检查引用数量
        citation_count = paper.get("citation_count", 0)
        if citation_count < min_citation_count:
            continue

        # 检查年份
        year = paper.get("year")
        if min_year and year and year < min_year:
            continue

        # 检查摘要
        if require_abstract and not paper.get("abstract"):
            continue

        filtered_papers.append(paper)

    filtered_ids = [p.get("id") for p in filtered_papers]

    logger.info(
        "Filtering completed",
        original_count=len(state.paper_ids),
        filtered_count=len(filtered_ids),
        removed=len(state.paper_ids) - len(filtered_ids),
    )

    return {
        "filtered_paper_ids": filtered_ids,
        "paper_ids": filtered_ids,
        "status": "filtered",
    }
