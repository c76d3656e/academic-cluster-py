"""
证据卡片节点 - 为论文生成结构化证据卡片

支持幂等恢复：跳过已有证据卡片的论文。
"""

import asyncio
import traceback

import structlog

from ...agents.evidence_generation import CORE_EVIDENCE_CARD_TARGET, generate_evidence_cards_batch
from ...services.database import get_database
from ...services.observability import get_current_tracker
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()


def _select_evidence_paper_ids(state: PipelineState, target: int = CORE_EVIDENCE_CARD_TARGET) -> list[str]:
    """Select core papers only for evidence cards, preserving core ranking order."""
    selected: list[str] = []
    seen: set[str] = set()
    for paper_id in list(state.core_paper_ids or []):
        if paper_id and paper_id not in seen:
            selected.append(paper_id)
            seen.add(paper_id)
        if len(selected) >= target:
            break
    return selected


async def evidence_cards_node(state: PipelineState) -> dict:
    """
    生成证据卡片

    使用 LLM 为每篇核心论文生成结构化证据卡片。
    支持幂等恢复：查询 DB 跳过已有卡片的论文。
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("evidence_cards", "llm", index=6)

    evidence_paper_ids = _select_evidence_paper_ids(state)
    if not evidence_paper_ids and state.reranked_paper_ids:
        logger.warning("No core papers available for evidence cards; refusing to use reranked fallback")

    logger.info(
        "Starting evidence card generation",
        evidence_papers=len(evidence_paper_ids),
        core_papers=len(state.core_paper_ids),
        auxiliary_papers=len(state.auxiliary_paper_ids),
        target=CORE_EVIDENCE_CARD_TARGET,
    )
    if len(evidence_paper_ids) < CORE_EVIDENCE_CARD_TARGET:
        logger.warning(
            "Evidence paper count below target",
            evidence_papers=len(evidence_paper_ids),
            target=CORE_EVIDENCE_CARD_TARGET,
        )

    db = get_database()

    # 获取核心论文详情
    papers = await db.get_papers_by_ids(evidence_paper_ids)

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
                text("""
                    SELECT id, paper_id
                    FROM evidence_cards
                    WHERE project_id = :project_id AND paper_id = ANY(:pids)
                """),
                {"project_id": state.project_id, "pids": paper_ids_to_check}
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
        await send_progress(
            state.project_id, "evidence_cards",
            f"为 {len(remaining_papers)} 篇论文生成证据卡片...",
        )

        # 批量生成证据卡片（只处理剩余论文）
        try:
            requested_concurrency = int((state.config or {}).get("evidence_concurrency", -1))
        except (TypeError, ValueError):
            requested_concurrency = -1
        from ...services.provider_pool import get_llm_available_slots
        provider_slots = get_llm_available_slots(default=10)
        concurrency = provider_slots if requested_concurrency <= 0 else min(requested_concurrency, provider_slots)
        concurrency = max(1, concurrency)
        logger.info(
            "Evidence card concurrency resolved",
            requested=requested_concurrency,
            provider_slots=provider_slots,
            effective=concurrency,
            mode="auto" if requested_concurrency <= 0 else "fixed",
        )

        try:
            timeout_s = int((state.config or {}).get("evidence_timeout_s", 120))
        except (TypeError, ValueError):
            timeout_s = 120

        def _progress(completed: int, total: int):
            asyncio.ensure_future(send_progress(
                state.project_id, "evidence_cards",
                f"证据卡片生成中 {completed}/{total}...",
                progress=completed / total if total > 0 else 0,
            ))

        evidence_cards = await generate_evidence_cards_batch(
            remaining_papers,
            concurrency=concurrency,
            timeout_s=timeout_s,
            progress_callback=_progress,
        )

        # 构建 paper_id → cluster_id 映射
        paper_cluster_map = {}
        if state.cluster_ids:
            clusters = await db.get_clusters_by_ids(state.cluster_ids)
            for cluster in clusters:
                for pid in cluster.get("paper_ids") or []:
                    paper_cluster_map[pid] = cluster.get("id", "")

        # 保存到数据库
        new_card_ids = []
        for card in evidence_cards:
            pid = card.get("paper_id", "")
            card["project_id"] = state.project_id
            card["cluster_id"] = paper_cluster_map.get(pid, "")
            card_id = await db.save_evidence_card(card)
            new_card_ids.append(card_id)

        # 合并已有 + 新生成
        all_card_ids = existing_card_ids + new_card_ids

        if len(all_card_ids) < len(papers):
            logger.warning(
                "Evidence cards below core paper count",
                total_cards=len(all_card_ids),
                evidence_papers=len(papers),
            )

        logger.info(
            "Evidence card generation completed",
            new_cards=len(new_card_ids),
            total_cards=len(all_card_ids),
            skipped_papers=len(already_done_paper_ids),
        )

        await send_progress(
            state.project_id, "evidence_cards",
            f"证据卡片生成完成，共 {len(all_card_ids)} 张",
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
        raise
