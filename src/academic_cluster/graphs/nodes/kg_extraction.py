"""
知识图谱提取节点 - 从论文中提取实体和关系

并发模式：同时发出 K 个请求，每个请求处理 1 篇论文。
配合幂等恢复，中断后只处理未完成的论文。
"""

import asyncio

import structlog

from ...agents.kg_extraction import extract_kg_from_papers_batch, normalize_kg
from ...api.sse import get_sse_manager
from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def kg_extraction_node(state: PipelineState) -> dict:
    """
    知识图谱提取

    将论文按 KG_BATCH_SIZE 分批，每批打包成一个 LLM prompt。
    支持幂等恢复：开始时查询 DB 跳过已提取的论文。
    """
    logger.info("Starting KG extraction", paper_count=len(state.core_paper_ids))

    from ...config import get_settings
    settings = get_settings()
    config = state.config or {}
    project_id = state.project_id

    # 并发度：同时发出 K 个 LLM 请求（默认 10，100 RPM / 60s ≈ 安全值）
    concurrency = config.get("kg_concurrency", 10)

    db = get_database()

    # 获取核心论文详情
    papers = await db.get_papers_by_ids(state.core_paper_ids)

    if not papers:
        logger.warning("No papers for KG extraction")
        return {
            "kg_entity_ids": [],
            "kg_relation_ids": [],
            "status": "kg_extracted",
        }

    # === 幂等恢复：查询已提取 KG 的论文，跳过 ===
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
                {"pids": paper_ids_to_check}
            )
            already_extracted_paper_ids = {str(row[0]) for row in result.fetchall()}

        if already_extracted_paper_ids:
            # 收集已有的实体和关系 ID
            async with db.session() as session:
                result = await session.execute(
                    text("""SELECT id FROM kg_entities
                            WHERE paper_ids && :pids"""),
                    {"pids": paper_ids_to_check}
                )
                existing_entity_ids = [str(row[0]) for row in result.fetchall()]

                result = await session.execute(
                    text("""SELECT id FROM kg_relations
                            WHERE paper_ids && :pids"""),
                    {"pids": paper_ids_to_check}
                )
                existing_relation_ids = [str(row[0]) for row in result.fetchall()]

            logger.info(
                "Resuming KG extraction, skipping already processed papers",
                already_done=len(already_extracted_paper_ids),
                total=len(papers),
                existing_entities=len(existing_entity_ids),
            )
    except Exception as e:
        logger.warning("Failed to check existing KG, processing all papers", error=str(e))
        already_extracted_paper_ids = set()

    # 过滤掉已处理的论文
    remaining_papers = [p for p in papers if p["id"] not in already_extracted_paper_ids]
    if not remaining_papers:
        logger.info("All papers already have KG, skipping extraction")
        return {
            "kg_entity_ids": existing_entity_ids,
            "kg_relation_ids": existing_relation_ids,
            "status": "kg_extracted",
        }

    # SSE 进度回调
    sse_manager = get_sse_manager()

    async def progress_callback(current: int, total: int, message: str):
        await sse_manager.send_progress(
            project_id=project_id,
            node="kg_extraction",
            status="processing",
            progress=current / total if total > 0 else 0,
            message=message,
        )

    try:
        all_raw_entities = []
        all_raw_relations = []
        total = len(remaining_papers)
        completed_count = 0
        completed_lock = asyncio.Lock()

        semaphore = asyncio.Semaphore(concurrency)

        async def extract_one(idx: int, paper: dict) -> dict | None:
            """提取单篇论文的 KG，受信号量控制并发"""
            nonlocal completed_count
            async with semaphore:
                try:
                    result = await extract_kg_from_papers_batch([paper])

                    # 设置 paper_ids
                    for entity in result.get("entities", []):
                        pid = entity.get("paper_id", "")
                        entity["paper_ids"] = [pid] if pid else []
                    for rel in result.get("relations", []):
                        pid = rel.get("paper_id", "")
                        rel["paper_ids"] = [pid] if pid else []

                    async with completed_lock:
                        completed_count += 1
                        if progress_callback:
                            await progress_callback(
                                completed_count,
                                total,
                                f"KG extraction: {completed_count}/{total} papers done (concurrency={concurrency})",
                            )

                    return result
                except Exception as e:
                    logger.error("KG extraction failed for paper", paper_idx=idx, error=str(e))
                    async with completed_lock:
                        completed_count += 1
                    return None

        # 并发发出所有请求
        tasks = [extract_one(i, paper) for i, paper in enumerate(remaining_papers)]
        results = await asyncio.gather(*tasks)

        # 收集结果
        for result in results:
            if result is not None:
                all_raw_entities.extend(result.get("entities", []))
                all_raw_relations.extend(result.get("relations", []))

        # 规范化和去重
        normalized = normalize_kg(all_raw_entities, all_raw_relations)
        entities = normalized["entities"]
        relations = normalized["relations"]

        # 记录 token 用量
        from ...agents.kg_extraction import get_token_tracker
        tracker = get_token_tracker()
        token_usage = tracker.summary()
        if token_usage:
            logger.info(
                "KG extraction token usage",
                prompt_tokens=token_usage.get("prompt_tokens", 0),
                completion_tokens=token_usage.get("completion_tokens", 0),
                total_tokens=token_usage.get("total_tokens", 0),
                call_count=token_usage.get("call_count", 0),
            )

        # 保存实体到数据库
        entity_ids = await db.save_kg_entities(entities)

        # 构建实体名称到 ID 的映射
        entity_name_to_id = {}
        for entity, entity_id in zip(entities, entity_ids):
            entity_name_to_id[entity.get("normalized_name", "")] = entity_id

        # 更新关系的实体 ID
        from ...agents.kg_extraction import normalized_name as norm_name
        for relation in relations:
            source_key = relation.get("source", "")
            target_key = relation.get("target", "")
            source_norm = norm_name(source_key)
            target_norm = norm_name(target_key)
            relation["source_entity_id"] = entity_name_to_id.get(source_norm)
            relation["target_entity_id"] = entity_name_to_id.get(target_norm)

        # 只保存有有效实体 ID 的关系
        valid_relations = [
            r for r in relations
            if r.get("source_entity_id") and r.get("target_entity_id")
        ]
        relation_ids = await db.save_kg_relations(valid_relations)

        # 合并已有 + 新提取的 ID
        all_entity_ids = existing_entity_ids + entity_ids
        all_relation_ids = existing_relation_ids + relation_ids

        logger.info(
            "KG extraction completed",
            new_entities=len(entity_ids),
            new_relations=len(relation_ids),
            total_entities=len(all_entity_ids),
            total_relations=len(all_relation_ids),
            skipped_papers=len(already_extracted_paper_ids),
            dropped_relations=normalized["stats"]["dropped_relations"],
        )

        # 推送完成进度
        token_summary = token_usage.get("total_tokens", 0)
        await sse_manager.send_progress(
            project_id=project_id,
            node="kg_extraction",
            status="completed",
            progress=1.0,
            message=(
                f"KG extraction done: {len(all_entity_ids)} entities, "
                f"{len(all_relation_ids)} relations, {token_summary} tokens"
            ),
        )

        return {
            "kg_entity_ids": all_entity_ids,
            "kg_relation_ids": all_relation_ids,
            "status": "kg_extracted",
        }

    except Exception as e:
        logger.error("KG extraction failed", error=str(e))
        return {
            "kg_entity_ids": existing_entity_ids,
            "kg_relation_ids": existing_relation_ids,
            "status": "kg_extracted",
            "errors": [f"KG extraction failed: {str(e)}"],
        }
