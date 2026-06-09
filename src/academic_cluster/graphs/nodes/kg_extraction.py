"""
知识图谱提取节点 - 从论文中提取实体和关系
"""

import structlog

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

    # TODO: 实现知识图谱提取
    # 1. 从数据库获取核心论文的摘要
    # 2. 批量调用 LLM 提取实体和关系
    # 3. 解析 JSON 响应（支持修复）
    # 4. 实体标准化和去重
    # 5. 存储到数据库
    # 6. 返回实体和关系 ID 列表

    batch_size = state.config.get("kg_batch_size", 16)

    kg_entity_ids = []
    kg_relation_ids = []

    logger.info(
        "KG extraction completed",
        entities=len(kg_entity_ids),
        relations=len(kg_relation_ids),
    )

    return {
        "kg_entity_ids": kg_entity_ids,
        "kg_relation_ids": kg_relation_ids,
        "status": "kg_extracted",
    }
