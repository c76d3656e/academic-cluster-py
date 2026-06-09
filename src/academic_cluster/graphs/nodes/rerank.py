"""
重排序节点 - 使用 Rerank 模型对论文进行重排序
"""

import structlog

from ..state import PipelineState

logger = structlog.get_logger()


async def rerank_node(state: PipelineState) -> dict:
    """
    重排序论文

    使用 Rerank 模型（如 BAAI/bge-reranker-v2-m3）对论文进行重排序：
    - 计算查询与论文的相关性分数
    - 按分数排序
    - 分为核心参考（top 80）和辅助参考（next 160）
    """
    logger.info("Starting reranking", paper_count=len(state.paper_ids))

    # TODO: 实现重排序
    # 1. 从数据库获取论文标题和摘要
    # 2. 批量调用 Rerank API
    # 3. 按分数排序
    # 4. 分为核心和辅助参考

    core_count = state.config.get("core_reference_count", 80)
    auxiliary_count = state.config.get("auxiliary_reference_count", 160)

    # 暂时简单分割
    core_paper_ids = state.paper_ids[:core_count]
    auxiliary_paper_ids = state.paper_ids[core_count:core_count + auxiliary_count]

    logger.info(
        "Reranking completed",
        core_count=len(core_paper_ids),
        auxiliary_count=len(auxiliary_paper_ids),
    )

    return {
        "core_paper_ids": core_paper_ids,
        "auxiliary_paper_ids": auxiliary_paper_ids,
        "status": "reranked",
    }
