"""
大纲生成节点 - 生成综述大纲
"""

import structlog

from ...agents.writing import generate_outline
from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def outline_generation_node(state: PipelineState) -> dict:
    """
    生成综述大纲

    使用 LLM 基于聚类结果和知识图谱生成综述大纲：
    - 分析每个社区的主要主题
    - 确定章节结构
    - 生成章节描述和关键点
    - 确定每个章节对应的社区

    生成大纲后，图会中断等待用户确认。
    """
    logger.info("Starting outline generation")

    db = get_database()

    try:
        # 获取聚类信息
        clusters = []
        for cluster_id in state.cluster_ids:
            # TODO: 从数据库获取聚类详情
            clusters.append({
                "id": cluster_id,
                "name": "Cluster",
                "main_topics": [],
                "size": 0,
            })

        # 获取知识图谱摘要
        kg_summary = {
            "entity_types": [],
            "relation_types": [],
        }

        # 生成大纲
        outline_data = await generate_outline(
            topic=state.query,
            clusters=clusters,
            kg_summary=kg_summary,
        )

        # 保存大纲
        outline_id = await db.save_outline(outline_data)

        logger.info("Outline generation completed", outline_id=outline_id)

        return {
            "outline_id": outline_id,
            "status": "outline_generated",
        }

    except Exception as e:
        logger.error("Outline generation failed", error=str(e))
        return {
            "outline_id": None,
            "status": "outline_generated",
            "errors": [f"Outline generation failed: {str(e)}"],
        }
