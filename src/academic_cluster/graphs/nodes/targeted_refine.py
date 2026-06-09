"""
针对性精炼节点 - 根据差距分析补充搜索
"""

import structlog

from ...tools.academic_search import search_all_sources
from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def targeted_refine_node(state: PipelineState) -> dict:
    """
    针对性精炼

    根据差距分析结果进行补充搜索：
    - 使用生成的针对性查询搜索
    - 过滤和重排序新论文
    - 合并到现有论文列表

    预算限制：
    - 每个社区最多 2 次尝试
    - 整个运行最多 5 次
    """
    logger.info(
        "Starting targeted refinement",
        attempt=state.refinement_attempt + 1,
        max_attempts=state.max_refinement_attempts,
    )

    config = state.config or {}
    limit_per_source = config.get("targeted_search_limit", 20)

    db = get_database()

    try:
        # 生成针对性查询（简化版本）
        targeted_queries = [
            f"{state.query} methods",
            f"{state.query} applications",
            f"{state.query} challenges",
        ]

        # 搜索新论文
        new_papers = []
        for query in targeted_queries:
            papers = await search_all_sources(
                query=query,
                limit_per_source=limit_per_source,
                sources=["semantic_scholar", "arxiv"],
            )
            new_papers.extend(papers)

        # 去重（排除已有论文）
        existing_paper_ids = set(state.paper_ids)
        unique_new_papers = []

        for paper in new_papers:
            paper_id = paper.get("id")
            if paper_id and paper_id not in existing_paper_ids:
                unique_new_papers.append(paper)
                existing_paper_ids.add(paper_id)

        # 保存新论文
        new_paper_ids = []
        for paper in unique_new_papers[:50]:  # 限制数量
            try:
                await db.save_paper(paper)
                new_paper_ids.append(paper.get("id"))
            except Exception as e:
                logger.warning("Failed to save targeted paper", error=str(e))

        logger.info(
            "Targeted refinement completed",
            new_papers=len(new_paper_ids),
            attempt=state.refinement_attempt + 1,
        )

        return {
            "paper_ids": new_paper_ids,
            "refinement_attempt": state.refinement_attempt + 1,
            "needs_targeted_refinement": False,
            "status": "refined",
        }

    except Exception as e:
        logger.error("Targeted refinement failed", error=str(e))
        return {
            "paper_ids": [],
            "refinement_attempt": state.refinement_attempt + 1,
            "needs_targeted_refinement": False,
            "status": "refined",
            "errors": [f"Targeted refinement failed: {str(e)}"],
        }
