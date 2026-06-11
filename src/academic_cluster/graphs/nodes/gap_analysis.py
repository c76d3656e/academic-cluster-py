"""
差距分析节点 - 评估社区的证据完整性
"""

import traceback

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
    tracker = state.tracker if hasattr(state, 'tracker') else None
    if tracker:
        await tracker.begin_node("gap_analysis", "compute", index=7)

    logger.info("Starting gap analysis")

    db = get_database()

    try:
        # 获取聚类和证据信息
        clusters = await db.get_clusters_by_ids(state.cluster_ids)
        evidence_cards = await db.get_evidence_cards_by_ids(state.evidence_card_ids)

        # 分析每个聚类的证据覆盖情况
        cluster_evidence_map = {}
        for card in evidence_cards:
            cluster_id = card.get("cluster_id")
            if cluster_id:
                if cluster_id not in cluster_evidence_map:
                    cluster_evidence_map[cluster_id] = []
                cluster_evidence_map[cluster_id].append(card)

        # 计算证据覆盖率
        clusters_with_evidence = len(cluster_evidence_map)
        total_clusters = len(clusters)
        evidence_ratio = clusters_with_evidence / max(total_clusters, 1)

        # 检查每个聚类的证据质量
        gaps = []
        for cluster in clusters:
            cluster_id = cluster.get("id")
            cards = cluster_evidence_map.get(cluster_id, [])
            if len(cards) < 2:  # 每个聚类至少需要2个证据卡片
                gaps.append({
                    "cluster_id": cluster_id,
                    "cluster_name": cluster.get("name"),
                    "evidence_count": len(cards),
                    "needed": 2 - len(cards),
                })

        needs_refinement = len(gaps) > 0

        # 检查 refinement 尝试次数
        if state.refinement_attempt >= state.max_refinement_attempts:
            needs_refinement = False

        logger.info(
            "Gap analysis completed",
            total_clusters=total_clusters,
            clusters_with_evidence=clusters_with_evidence,
            evidence_ratio=evidence_ratio,
            gaps=len(gaps),
            needs_refinement=needs_refinement,
            attempt=state.refinement_attempt,
        )

        result = {
            "gap_analysis_ids": [g.get("cluster_id") for g in gaps],
            "needs_targeted_refinement": needs_refinement,
            "status": "gaps_analyzed",
        }
        if tracker:
            await tracker.end_node("gap_analysis", "succeeded", output_summary={
                "gaps": len(gaps),
                "needs_refinement": needs_refinement,
            })
        return result

    except Exception as e:
        if tracker:
            await tracker.end_node("gap_analysis", "failed",
                                   error_message=str(e),
                                   error_traceback=traceback.format_exc())
        logger.error("Gap analysis failed", error=str(e))
        raise  # 不再 fallback，直接抛出异常
