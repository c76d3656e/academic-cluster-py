"""
BM25 节点 - 使用 BM25 文本检索筛选论文
"""

import structlog

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

    # TODO: 实现 BM25 检索
    # 1. 从数据库获取论文标题和摘要
    # 2. 使用 rank_bm25 或 tantivy 构建索引
    # 3. 计算 BM25 分数
    # 4. 返回 Top-K 论文 ID

    # 使用配置中的最大嵌入论文数
    max_papers = state.config.get("max_embedding_papers", 500)

    bm25_selected_ids = state.filtered_paper_ids[:max_papers]  # 暂时截断

    logger.info(
        "BM25 selection completed",
        input_count=len(state.filtered_paper_ids),
        selected_count=len(bm25_selected_ids),
    )

    return {
        "paper_ids": bm25_selected_ids,
        "status": "bm25_selected",
    }
