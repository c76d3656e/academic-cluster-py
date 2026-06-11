"""
证据卡片节点 - 为论文生成结构化证据卡片

支持幂等恢复：跳过已有证据卡片的论文。
"""

import traceback

import structlog

from ...agents.evidence_generation import generate_evidence_cards_batch
from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def evidence_cards_node(state: PipelineState) -> dict:
    """
    生成证据卡片

    使用 LLM 为每篇核心论文生成结构化证据卡片。
    支持幂等恢复：查询 DB 跳过已有卡片的论文。
    """
    tracker = state.tracker if hasattr(state, 'tracker') else None
    if tracker:
        await tracker.begin_node("evidence_cards", "llm", index=6)

    logger.info("Starting evidence card generation", core_papers=len(state.core_paper_ids))

    db = get_database()

    # 获取核心论文详情
    papers = await db.get_papers_by_ids(state.core_paper_ids)

    if not papers:
        logger.warning("No papers for evidence generation")
        return {
            "evidence_card_ids": [],
            "status": "evidence_generated",
        }

    # === 幂等恢复：查询已有证据卡片，跳过 ===
    existing_card_ids = []
    already_done_paper_ids = set()

    try:
        paper_ids_to_check = [p["id"] for p in papers]
        async with db.session() as session:
            from sqlalchemy import text
            result = await session.execute(
                text("SELECT id, paper_id FROM evidence_cards WHERE paper_id = ANY(:pids)"),
                {"pids": paper_ids_to_check}
            )
            rows = result.fetchall()
            for row in rows:
                existing_card_ids.append(str(row[0]))
                already_done_paper_ids.add(str(row[1]))

        if already_done_paper_ids:
            logger.info(
                "Resuming evidence generation, skipping already processed papers",
                already_done=len(already_done_paper_ids),
                total=len(papers),
                existing_cards=len(existing_card_ids),
            )
    except Exception as e:
        logger.warning("Failed to check existing evidence cards, processing all", error=str(e))
        already_done_paper_ids = set()

    # 过滤掉已处理的论文
    remaining_papers = [p for p in papers if p["id"] not in already_done_paper_ids]
    if not remaining_papers:
        logger.info("All papers already have evidence cards, skipping")
        result = {
            "evidence_card_ids": existing_card_ids,
            "status": "evidence_generated",
        }
        if tracker:
            await tracker.end_node("evidence_cards", "succeeded", output_summary={
                "card_count": len(existing_card_ids),
                "skipped": True,
            })
        return result

    try:
        # 批量生成证据卡片（只处理剩余论文）
        evidence_cards = await generate_evidence_cards_batch(remaining_papers)

        # 构建 paper_id → cluster_id 映射
        paper_cluster_map = {}
        if state.cluster_ids:
            clusters = await db.get_clusters_by_ids(state.cluster_ids)
            for cluster in clusters:
                for pid in cluster.get("paper_ids", []):
                    paper_cluster_map[pid] = cluster.get("id", "")

        # 保存到数据库
        new_card_ids = []
        for card in evidence_cards:
            pid = card.get("paper_id", "")
            card["cluster_id"] = paper_cluster_map.get(pid, "")
            card_id = await db.save_evidence_card(card)
            new_card_ids.append(card_id)

        # 合并已有 + 新生成
        all_card_ids = existing_card_ids + new_card_ids

        logger.info(
            "Evidence card generation completed",
            new_cards=len(new_card_ids),
            total_cards=len(all_card_ids),
            skipped_papers=len(already_done_paper_ids),
        )

        result = {
            "evidence_card_ids": all_card_ids,
            "status": "evidence_generated",
        }
        if tracker:
            await tracker.end_node("evidence_cards", "succeeded", output_summary={
                "new_cards": len(new_card_ids),
                "total_cards": len(all_card_ids),
            })
        return result

    except Exception as e:
        if tracker:
            await tracker.end_node("evidence_cards", "failed",
                                   error_message=str(e),
                                   error_traceback=traceback.format_exc())
        logger.error("Evidence generation failed", error=str(e))
        return {
            "evidence_card_ids": existing_card_ids,
            "status": "evidence_generated",
            "errors": [f"Evidence generation failed: {str(e)}"],
        }
