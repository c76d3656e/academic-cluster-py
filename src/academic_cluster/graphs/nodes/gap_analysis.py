"""
差距分析节点 - 评估社区的证据完整性
"""

import structlog

from ..state import PipelineState

logger = structlog.get_logger()


async def gap_analysis_node(state: PipelineState) -> dict:
    """
    社区差距分析

    使用 LLM 评估每个社区的证据完整性：
    - 检查每个社区是否有足够的证据支持
    - 识别缺失的证据类型
    - 生成针对性搜索查询
    - 决定是否需要补充搜索
    """
    logger.info("Starting gap analysis")

    # TODO: 实现差距分析
    # 1. 从数据库获取聚类和证据卡片
    # 2. 使用 LLM 评估每个社区的完整性
    # 3. 生成差距分析报告
    # 4. 决定是否需要针对性搜索

    gap_analysis_ids = []
    needs_refinement = False

    # 检查是否还有 refinement 尝试次数
    if needs_refinement and state.refinement_attempt < state.max_refinement_attempts:
        logger.info("Gaps detected, refinement needed")
    else:
        logger.info("No significant gaps, proceeding to writing")

    return {
        "gap_analysis_ids": gap_analysis_ids,
        "needs_targeted_refinement": needs_refinement,
        "status": "gaps_analyzed",
    }
