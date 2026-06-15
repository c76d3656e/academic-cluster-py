"""
BM25 节点 - 使用 BM25 文本检索筛选论文
"""

import structlog

from ...services.database import get_database
from ...tools.text_processing import bm25_search
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()


async def bm25_node(state: PipelineState) -> dict:
    """
    BM25 文本检索评分与筛选

    使用 BM25 算法对所有过滤后的论文评分：
    - 构建内存索引（标题 + 摘要）
    - 计算查询与每篇论文的 BM25 分数
    - 按可配置阈值筛选掉低分论文
    - 保留 BM25 分数供后续 rerank 使用
    """
    logger.info("Starting BM25 scoring", paper_count=len(state.filtered_paper_ids))

    config = state.config or {}
    min_score = config.get("bm25.min_score", 0.5)
    max_papers = config.get("bm25.max_papers", 2000)

    db = get_database()
    papers = await db.get_papers_by_ids(state.filtered_paper_ids)

    if not papers:
        logger.warning("No papers to process")
        return {
            "paper_ids": [],
            "status": "bm25_scored",
        }

    # BM25 评分（返回全部，按分数排序）
    results = await bm25_search(
        query=state.query,
        documents=papers,
        top_k=len(papers),
    )

    # 按阈值筛选
    above_threshold = [p for p in results if p.get("bm25_score", 0) >= min_score]

    # 如果阈值筛选后太少，保留 top max_papers
    if len(above_threshold) < 20:
        logger.warning("BM25 threshold too strict, using top papers", above_threshold=len(above_threshold))
        above_threshold = results[:max_papers]

    # 安全阀：最多 max_papers 篇进入 embedding
    if len(above_threshold) > max_papers:
        above_threshold = above_threshold[:max_papers]

    bm25_ids = [p.get("id") for p in above_threshold]

    logger.info(
        "BM25 scoring completed",
        total_scored=len(results),
        above_threshold=len(bm25_ids),
        min_score=min_score,
    )

    await send_progress(
        state.project_id, "bm25",
        f"BM25 评分完成：{len(results)} 篇评分，{len(bm25_ids)} 篇高于阈值 {min_score}",
    )

    return {
        "paper_ids": bm25_ids,
        "status": "bm25_scored",
    }
