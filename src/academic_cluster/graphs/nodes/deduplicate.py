"""
去重节点 - 去除重复论文
"""

import structlog

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

    # TODO: 实现去重逻辑
    # 1. 从数据库获取论文详情
    # 2. 基于 DOI 去重
    # 3. 基于标题相似度去重
    # 4. 返回去重后的论文 ID 列表

    deduplicated_ids = state.paper_ids  # 暂时返回原始列表

    logger.info(
        "Deduplication completed",
        original_count=len(state.paper_ids),
        deduplicated_count=len(deduplicated_ids),
    )

    return {
        "paper_ids": deduplicated_ids,
        "status": "deduplicated",
    }
