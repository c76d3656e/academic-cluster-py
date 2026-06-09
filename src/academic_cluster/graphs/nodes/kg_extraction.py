"""
知识图谱提取节点 - 从论文中提取实体和关系
"""

import asyncio

import structlog

from ...agents.kg_extraction import extract_kg_batch
from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def kg_extraction_node(state: PipelineState) -> dict:
    """
    知识图谱提取

    使用 LLM 从论文中提取实体和关系：
    - 实体类型：ResearchProblem, Method, Dataset, Metric, Material, Concept, Domain
    - 关系类型：uses, evaluated_on, improves, applied_to, based_on, proposes, compares_with
    - 批量处理，支持 JSON 修复
    - 实体标准化和去重
    """
    logger.info("Starting KG extraction", paper_count=len(state.core_paper_ids))

    config = state.config or {}
    batch_size = config.get("kg_batch_size", 16)

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

    try:
        # 批量提取知识图谱
        kg_results = await extract_kg_batch(papers, batch_size=batch_size)

        entities = kg_results.get("entities", [])
        relations = kg_results.get("relations", [])

        # 添加论文引用
        for entity in entities:
            entity["paper_ids"] = [
                p.get("id") for p in papers
                if entity.get("normalized_name", "").lower() in
                (p.get("title", "") + " " + p.get("abstract", "")).lower()
            ]

        # 保存到数据库
        entity_ids = await db.save_kg_entities(entities)
        relation_ids = await db.save_kg_relations(relations)

        logger.info(
            "KG extraction completed",
            entities=len(entity_ids),
            relations=len(relation_ids),
        )

        return {
            "kg_entity_ids": entity_ids,
            "kg_relation_ids": relation_ids,
            "status": "kg_extracted",
        }

    except Exception as e:
        logger.error("KG extraction failed", error=str(e))
        return {
            "kg_entity_ids": [],
            "kg_relation_ids": [],
            "status": "kg_extracted",
            "errors": [f"KG extraction failed: {str(e)}"],
        }
