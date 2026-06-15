"""
差距分析节点 - 评估社区的证据完整性

对齐 Rust 版 community_gap_analysis：
- 复用 community_detection 的 4 类 gap 检测逻辑
- LLM judge 确认或软化 gap 决策
- 生成针对性搜索查询
"""

import traceback

import structlog

from ...services.database import get_database
from ...services.observability import get_current_tracker
from ..state import PipelineState
logger = structlog.get_logger()


def _analyze_community_gaps(
    clusters: list[dict],
    evidence_cards: list[dict],
    kg_entities: list[dict],
    papers: list[dict],
) -> list[dict]:
    paper_evidence_map: dict[str, list[dict]] = {}
    for card in evidence_cards:
        pid = str(card.get("paper_id", ""))
        if pid:
            paper_evidence_map.setdefault(pid, []).append(card)

    paper_entity_count: dict[str, int] = {}
    for entity in kg_entities:
        for pid in entity.get("paper_ids") or []:
            pid = str(pid)
            paper_entity_count[pid] = paper_entity_count.get(pid, 0) + 1

    gap_reports = []
    for cluster in clusters:
        cluster_paper_ids = {str(pid) for pid in cluster.get("paper_ids", [])}
        paper_count = len(cluster_paper_ids)
        cluster_evidence = []
        for pid in cluster_paper_ids:
            cluster_evidence.extend(paper_evidence_map.get(pid, []))

        confidences = []
        for card in cluster_evidence:
            try:
                confidences.append(float(card.get("confidence", 0.0) or 0.0))
            except (TypeError, ValueError):
                confidences.append(0.0)
        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        entity_count = sum(paper_entity_count.get(pid, 0) for pid in cluster_paper_ids)

        gap_type = None
        if paper_count < 3:
            gap_type = "small_community"
        elif len(cluster_evidence) < min(paper_count, 3):
            gap_type = "missing_evidence_cards"
        elif avg_confidence < 0.45:
            gap_type = "low_evidence_confidence"
        elif entity_count < 2:
            gap_type = "sparse_kg_entities"

        gap_reports.append({
            "cluster_id": cluster.get("id"),
            "status": "needs_refinement" if gap_type else "enough_evidence",
            "gap_type": gap_type,
            "paper_count": paper_count,
            "evidence_card_count": len(cluster_evidence),
            "avg_confidence": round(avg_confidence, 3),
            "entity_count": entity_count,
        })

    return gap_reports


async def _refine_gaps_with_llm(topic: str, gap_reports: list[dict]) -> list[dict]:
    from langchain_core.messages import HumanMessage, SystemMessage

    from ...services.llm_client import ainvoke_with_callbacks, create_llm
    from ...tools.json_repair import try_parse_json

    gap_communities = [r for r in gap_reports if r["status"] == "needs_refinement"]
    if not gap_communities:
        return gap_reports

    user_prompt = "\n".join(
        f'{r["cluster_id"]}: gap={r["gap_type"]}, papers={r["paper_count"]}, '
        f'evidence={r["evidence_card_count"]}, entities={r["entity_count"]}'
        for r in gap_communities
    )
    try:
        llm = create_llm(temperature=0.0, max_tokens=1024)
        response = await ainvoke_with_callbacks(llm, [
            SystemMessage(content="Return JSON only. Confirm or soften literature-review gap decisions."),
            HumanMessage(content=(
                f"Topic: {topic}\n\nCommunities:\n{user_prompt}\n\n"
                'Return {"decisions":[{"community_id":"...","status":"enough_evidence|needs_refinement","reason":"..."}]}'
            )),
        ])
        content = response.content
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        data = try_parse_json(content)
        if data and isinstance(data.get("decisions"), list):
            decision_map = {
                str(d.get("community_id")): d.get("status")
                for d in data["decisions"]
            }
            for report in gap_reports:
                if decision_map.get(str(report["cluster_id"])) == "enough_evidence":
                    report["status"] = "enough_evidence"
                    report["gap_type"] = None
    except Exception as e:
        logger.warning("LLM gap judge failed, keeping deterministic decisions", error=str(e))

    return gap_reports


async def gap_analysis_node(state: PipelineState) -> dict:
    """
    社区差距分析（对齐 Rust 版 community_gap_analysis）

    复用 community_detection 的完整 gap 分析逻辑：
    - small_community: paper_count < 3
    - missing_evidence_cards: evidence_card_count < min(paper_count, 3)
    - low_evidence_confidence: avg_confidence < 0.45
    - sparse_kg_entities: entity_count < 2

    在 targeted_refine 循环中，基于最新的 evidence cards 重新评估。
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("gap_analysis", "compute", index=7)

    logger.info("Starting gap analysis")

    db = get_database()

    try:
        # 获取聚类、证据、KG 实体
        clusters = await db.get_clusters_by_ids(state.cluster_ids)
        evidence_cards = await db.get_evidence_cards_by_ids(state.evidence_card_ids)
        kg_entities = await db.get_kg_entities_by_ids(state.kg_entity_ids)

        # 获取论文详情（用于 gap 分析）
        all_paper_ids = state.reranked_paper_ids or state.paper_ids
        papers = await db.get_papers_by_ids(all_paper_ids)

        # 复用 community_detection 的 gap 分析逻辑
        gap_reports = _analyze_community_gaps(clusters, evidence_cards, kg_entities, papers)
        gap_reports = await _refine_gaps_with_llm(state.query, gap_reports)

        needs_refinement = [r for r in gap_reports if r["status"] == "needs_refinement"]
        needs_refinement_flag = len(needs_refinement) > 0

        # 检查 refinement 尝试次数
        if state.refinement_attempt >= state.max_refinement_attempts:
            needs_refinement_flag = False

        # 如果上一轮 targeted_refine 没有找到新论文，不再触发（避免无意义循环）
        if state.refinement_attempt > 0 and not state.paper_ids:
            needs_refinement_flag = False

        # 提取弱聚类信息（供 targeted_refine 使用）
        weak_clusters = [
            {
                "cluster_id": r["cluster_id"],
                "gap_type": r["gap_type"],
                "paper_count": r["paper_count"],
                "evidence_card_count": r["evidence_card_count"],
            }
            for r in needs_refinement
        ]

        logger.info(
            "Gap analysis completed",
            total_clusters=len(clusters),
            gaps=len(needs_refinement),
            needs_refinement=needs_refinement_flag,
            attempt=state.refinement_attempt,
            gap_types=[r["gap_type"] for r in needs_refinement],
        )

        result = {
            "gap_analysis_ids": [r["cluster_id"] for r in needs_refinement],
            "needs_targeted_refinement": needs_refinement_flag,
            "gap_reports": gap_reports,
            "gap_analysis_result": {
                "gaps": [r["gap_type"] for r in needs_refinement],
                "weak_clusters": weak_clusters,
            },
            "status": "gaps_analyzed",
        }
        if tracker:
            await tracker.end_node("gap_analysis", "succeeded", output_summary={
                "gaps": len(needs_refinement),
                "needs_refinement": needs_refinement_flag,
            })
        return result

    except Exception as e:
        if tracker:
            await tracker.end_node("gap_analysis", "failed",
                                   error_message=str(e),
                                   error_traceback=traceback.format_exc())
        logger.error("Gap analysis failed", error=str(e))
        raise
