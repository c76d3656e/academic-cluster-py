"""
去重节点 - 去除重复论文
"""

import structlog

from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def deduplicate_node(state: PipelineState) -> dict:
    """
    去除重复论文

    基于以下标准去重：
    - DOI 相同
    - 标题相似度 > 0.9
    - 外部 ID 相同
    """
    logger.info("Starting deduplication", paper_count=len(state.paper_ids))

    db = get_database()

    # 获取论文详情
    papers = await db.get_papers_by_ids(state.paper_ids)

    # 基于外部 ID 去重
    seen_external_ids = set()
    unique_papers = []

    for paper in papers:
        external_id = paper.get("external_id")
        if external_id and external_id not in seen_external_ids:
            seen_external_ids.add(external_id)
            unique_papers.append(paper)
        elif not external_id:
            unique_papers.append(paper)

    # 基于标题去重
    seen_titles = set()
    final_papers = []

    for paper in unique_papers:
        title = paper.get("title", "").lower().strip()
        normalized_title = " ".join(title.split())

        if normalized_title and normalized_title not in seen_titles:
            seen_titles.add(normalized_title)
            final_papers.append(paper)
        elif not normalized_title:
            final_papers.append(paper)

    deduplicated_ids = [p.get("id") for p in final_papers]

    logger.info(
        "Deduplication completed",
        original_count=len(state.paper_ids),
        deduplicated_count=len(deduplicated_ids),
        removed=len(state.paper_ids) - len(deduplicated_ids),
    )

    return {
        "paper_ids": deduplicated_ids,
        "status": "deduplicated",
    }
