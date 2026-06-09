"""
针对性精炼节点 - 根据差距分析补充搜索
"""

import structlog

from ..state import PipelineState

logger = structlog.get_logger()


async def targeted_refine_node(state: PipelineState) -> dict:
    """
    针对性精炼

    根据差距分析结果进行补充搜索：
    - 使用生成的针对性查询搜索
    - 过滤和重排序新论文
    - 提取知识图谱
    - 生成证据卡片
    - 合并到现有聚类

    预算限制：
    - 每个社区最多 2 次尝试
    - 整个运行最多 5 次
    """
    logger.info(
        "Starting targeted refinement",
        attempt=state.refinement_attempt + 1,
        max_attempts=state.max_refinement_attempts,
    )

    # TODO: 实现针对性精炼
    # 1. 从数据库获取差距分析结果
    # 2. 使用针对性查询搜索新论文
    # 3. 过滤和重排序
    # 4. 提取知识图谱
    # 5. 生成证据卡片
    # 6. 合并到现有聚类

    new_paper_ids = []

    logger.info(
        "Targeted refinement completed",
        new_papers=len(new_paper_ids),
    )

    return {
        "paper_ids": new_paper_ids,
        "refinement_attempt": state.refinement_attempt + 1,
        "needs_targeted_refinement": False,  # 重置标志
        "status": "refined",
    }
