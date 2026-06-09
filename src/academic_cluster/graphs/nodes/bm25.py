"""
BM25 节点 - 使用 BM25 文本检索筛选论文
"""

import structlog

from ...services.database import get_database
from ...tools.text_processing import bm25_search
from ..state import PipelineState

logger = structlog.get_logger()


async def bm25_node(state: PipelineState) -> dict:
    """
    BM25 文本检索

    使用 BM25 算法对论文进行文本相似度排序：
    - 构建内存索引（标题 + 摘要）
    - 计算查询与论文的 BM25 分数
    - 选择 Top-K 论文
    """
    logger.info("Starting BM25 selection", paper_count=len(state.filtered_paper_ids))

    config = state.config or {}
    max_papers = config.get("max_embedding_papers", 500)

    db = get_database()
    papers = await db.get_papers_by_ids(state.filtered_paper_ids)

    if not papers:
        logger.warning("No papers to process")
        return {
            "paper_ids": [],
            "status": "bm25_selected",
        }

    # BM25 搜索
    results = await bm25_search(
        query=state.query,
        documents=papers,
        top_k=max_papers,
    )

    bm25_selected_ids = [p.get("id") for p in results]

    logger.info(
        "BM25 selection completed",
        input_count=len(state.filtered_paper_ids),
        selected_count=len(bm25_selected_ids),
    )

    return {
        "paper_ids": bm25_selected_ids,
        "status": "bm25_selected",
    }
