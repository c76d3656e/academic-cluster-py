"""
差距分析节点 - 评估社区的证据完整性
"""

import structlog

from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def gap_analysis_node(state: PipelineState) -> dict:
    """
    社区差距分析

    评估每个社区的证据完整性：
    - 检查每个社区是否有足够的证据支持
    - 识别缺失的证据类型
    - 生成针对性搜索查询
    - 决定是否需要补充搜索
    """
    logger.info("Starting gap analysis")

    db = get_database()

    try:
        # 获取聚类和证据信息
        clusters = []
        for cluster_id in state.cluster_ids:
            # TODO: 从数据库获取聚类详情
            pass

        evidence_cards = []
        for card_id in state.evidence_card_ids:
            # TODO: 从数据库获取证据卡片详情
            pass

        # 简化的差距分析逻辑
        # 如果证据卡片数量少于核心论文数量的 50%，认为有差距
        evidence_ratio = len(state.evidence_card_ids) / max(len(state.core_paper_ids), 1)
        needs_refinement = evidence_ratio < 0.5

        # 检查 refinement 尝试次数
        if state.refinement_attempt >= state.max_refinement_attempts:
            needs_refinement = False

        gap_analysis_ids = []

        logger.info(
            "Gap analysis completed",
            evidence_ratio=evidence_ratio,
            needs_refinement=needs_refinement,
            attempt=state.refinement_attempt,
        )

        return {
            "gap_analysis_ids": gap_analysis_ids,
            "needs_targeted_refinement": needs_refinement,
            "status": "gaps_analyzed",
        }

    except Exception as e:
        logger.error("Gap analysis failed", error=str(e))
        return {
            "gap_analysis_ids": [],
            "needs_targeted_refinement": False,
            "status": "gaps_analyzed",
            "errors": [f"Gap analysis failed: {str(e)}"],
        }
