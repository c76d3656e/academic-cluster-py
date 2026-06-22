"""
知识图谱提取节点 - 从论文中提取实体和关系
并发模式：同时发出 K 个请求，每个请求处理 1 篇论文。
配合幂等恢复，中断后只处理未完成的论文。
"""

import asyncio
import traceback

import structlog

from ...agents.kg_extraction import extract_kg_from_papers_batch, normalize_kg
from ...services.database import get_database
from ...services.observability import get_current_tracker
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()


async def kg_extraction_node(state: PipelineState) -> dict:
    """
    知识图谱提取

    将论文按 KG_BATCH_SIZE 分批，每批打包成一个 LLM prompt。
    支持幂等恢复：开始时查询 DB 跳过已提取的论文。
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("kg_extraction", "llm", index=3)

    from ...config import get_settings

    get_settings()
    config = state.config or {}
    project_id = state.project_id
    kg_scope = str(config.get("kg_scope", "core")).lower()
    if kg_scope == "reranked":
        kg_paper_ids = list(state.reranked_paper_ids or [])
    else:
        kg_paper_ids = list(state.core_paper_ids or [])

    logger.info(
        "Starting KG extraction",
        paper_count=len(kg_paper_ids),
        core_papers=len(state.core_paper_ids),
        scope=kg_scope,
    )

    # 骞跺彂搴︼細鍚屾椂鍙戝嚭 K 涓?LLM 璇锋眰锛堥粯璁?10锛?00 RPM / 60s 鈮?瀹夊叏鍊硷級
    try:
        requested_concurrency = int(config.get("kg_concurrency", -1))
    except (TypeError, ValueError):
        requested_concurrency = -1
    from ...services.provider_pool import get_llm_available_slots

    provider_slots = get_llm_available_slots(default=10)
    if requested_concurrency <= 0:
        concurrency = provider_slots
        concurrency_mode = "auto"
    else:
        concurrency = min(requested_concurrency, provider_slots)
        concurrency_mode = "manual"
    concurrency = max(1, concurrency)
    logger.info(
        "KG extraction concurrency resolved",
        requested=requested_concurrency,
        provider_slots=provider_slots,
        effective=concurrency,
        mode=concurrency_mode,
    )

    db = get_database()

    papers = await db.get_papers_by_ids(kg_paper_ids)

    if not papers:
        logger.warning("No papers for KG extraction")
        return {
            "kg_entity_ids": [],
            "kg_relation_ids": [],
            "status": "kg_extracted",
        }

    # === 骞傜瓑鎭㈠锛氭煡璇㈠凡鎻愬彇 KG 鐨勮鏂囷紝璺宠繃 ===
    existing_entity_ids = []
    existing_relation_ids = []
    already_extracted_paper_ids = set()

    try:
        paper_ids_to_check = [p["id"] for p in papers]
        async with db.session() as session:
            from sqlalchemy import text

            result = await session.execute(
                text("""SELECT DISTINCT unnest(paper_ids) as pid
                        FROM kg_entities
                        WHERE paper_ids && :pids"""),
                {"pids": paper_ids_to_check},
            )
            already_extracted_paper_ids = {str(row[0]) for row in result.fetchall()}

        if already_extracted_paper_ids:
            # 鏀堕泦宸叉湁鐨勫疄浣撳拰鍏崇郴 ID
            async with db.session() as session:
                result = await session.execute(
                    text("""SELECT id FROM kg_entities
                            WHERE paper_ids && :pids"""),
                    {"pids": paper_ids_to_check},
                )
                existing_entity_ids = [str(row[0]) for row in result.fetchall()]

                result = await session.execute(
                    text("""SELECT id FROM kg_relations
                            WHERE paper_ids && :pids"""),
                    {"pids": paper_ids_to_check},
                )
                existing_relation_ids = [str(row[0]) for row in result.fetchall()]

            logger.info(
                "Resuming KG extraction, skipping already processed papers",
                already_done=len(already_extracted_paper_ids),
                total=len(papers),
                existing_entities=len(existing_entity_ids),
            )
    except Exception as e:
        logger.warning(
            "Failed to check existing KG, processing all papers", error=str(e)
        )
        already_extracted_paper_ids = set()

    # Skip papers that already have KG rows for idempotent resume.
    remaining_papers = [
        p for p in papers if str(p.get("id")) not in already_extracted_paper_ids
    ]
    if not remaining_papers:
        logger.info("All papers already have KG, skipping extraction")
        result = {
            "kg_entity_ids": existing_entity_ids,
            "kg_relation_ids": existing_relation_ids,
            "status": "kg_extracted",
        }
        if tracker:
            await tracker.end_node(
                "kg_extraction",
                "succeeded",
                output_summary={
                    "entities": len(existing_entity_ids),
                    "relations": len(existing_relation_ids),
                    "skipped": True,
                },
            )
        return result

    try:
        from ...agents.kg_extraction import normalized_name as norm_name

        new_entity_ids = []
        new_relation_ids = []
        total = len(remaining_papers)
        completed_count = 0
        completed_lock = asyncio.Lock()

        semaphore = asyncio.Semaphore(concurrency)

        async def extract_and_save(idx: int, paper: dict) -> None:
            """鎻愬彇鍗曠瘒璁烘枃鐨?KG 骞剁珛鍗冲啓鍏?DB锛屼腑鏂笉涓㈠け"""
            nonlocal completed_count
            async with semaphore:
                try:
                    result = await extract_kg_from_papers_batch([paper])

                    # 璁剧疆 paper_ids
                    for entity in result.get("entities", []):
                        pid = entity.get("paper_id", "")
                        entity["paper_ids"] = [pid] if pid else []
                    for rel in result.get("relations", []):
                        pid = rel.get("paper_id", "")
                        rel["paper_ids"] = [pid] if pid else []

                    # 绔嬪嵆鍐欏叆 DB
                    raw_entities = result.get("entities", [])
                    raw_relations = result.get("relations", [])
                    if raw_entities:
                        normalized = normalize_kg(raw_entities, raw_relations)
                        entities = normalized["entities"]
                        relations = normalized["relations"]

                        saved_entity_ids = await db.save_kg_entities(entities)

                        # 鏋勫缓瀹炰綋鍚嶇О鍒?ID 鏄犲皠
                        entity_name_to_id = {}
                        for entity, eid in zip(
                            entities, saved_entity_ids, strict=False
                        ):
                            entity_name_to_id[entity.get("normalized_name", "")] = eid

                        # 鏇存柊鍏崇郴鐨勫疄浣?ID
                        for relation in relations:
                            source_key = relation.get("source", "")
                            target_key = relation.get("target", "")
                            relation["source_entity_id"] = entity_name_to_id.get(
                                norm_name(source_key)
                            )
                            relation["target_entity_id"] = entity_name_to_id.get(
                                norm_name(target_key)
                            )

                        valid_relations = [
                            r
                            for r in relations
                            if r.get("source_entity_id") and r.get("target_entity_id")
                        ]
                        saved_relation_ids = (
                            await db.save_kg_relations(valid_relations)
                            if valid_relations
                            else []
                        )

                        async with completed_lock:
                            new_entity_ids.extend(saved_entity_ids)
                            new_relation_ids.extend(saved_relation_ids)

                    async with completed_lock:
                        completed_count += 1
                        await send_progress(
                            project_id,
                            "kg_extraction",
                            f"知识图谱抽取中 {completed_count}/{total}...",
                            progress=completed_count / total if total > 0 else 0,
                        )

                except Exception as e:
                    logger.error(
                        "KG extraction failed for paper", paper_idx=idx, error=str(e)
                    )
                    async with completed_lock:
                        completed_count += 1
                        await send_progress(
                            project_id,
                            "kg_extraction",
                            f"知识图谱抽取中 {completed_count}/{total}...",
                            progress=completed_count / total if total > 0 else 0,
                        )

        tasks = [extract_and_save(i, paper) for i, paper in enumerate(remaining_papers)]
        await asyncio.gather(*tasks)

        # 鍚堝苟宸叉湁 + 鏂版彁鍙栫殑 ID
        all_entity_ids = existing_entity_ids + new_entity_ids
        all_relation_ids = existing_relation_ids + new_relation_ids

        logger.info(
            "KG extraction completed",
            new_entities=len(new_entity_ids),
            new_relations=len(new_relation_ids),
            total_entities=len(all_entity_ids),
            total_relations=len(all_relation_ids),
            skipped_papers=len(already_extracted_paper_ids),
        )

        await send_progress(
            project_id,
            "kg_extraction",
            f"知识图谱抽取完成，{len(all_entity_ids)} 个实体，{len(all_relation_ids)} 条关系",
            progress=1.0,
        )

        result = {
            "kg_entity_ids": all_entity_ids,
            "kg_relation_ids": all_relation_ids,
            "status": "kg_extracted",
        }
        if tracker:
            await tracker.end_node(
                "kg_extraction",
                "succeeded",
                output_summary={
                    "entities": len(all_entity_ids),
                    "relations": len(all_relation_ids),
                },
            )
        return result

    except Exception as e:
        if tracker:
            await tracker.end_node(
                "kg_extraction",
                "failed",
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )
        logger.error("KG extraction failed", error=str(e))
        return {
            "kg_entity_ids": existing_entity_ids,
            "kg_relation_ids": existing_relation_ids,
            "status": "kg_extracted",
            "errors": [f"KG extraction failed: {e!s}"],
        }
