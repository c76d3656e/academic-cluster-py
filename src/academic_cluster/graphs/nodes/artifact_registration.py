"""
产出物注册节点 - 生成最终产出物
"""

import structlog

from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def artifact_registration_node(state: PipelineState) -> dict:
    """
    产出物注册

    生成并存储最终产出物：
    - 最终综述 Markdown
    - BibTeX 引用文件
    - 引用报告
    - 质量评估
    """
    logger.info("Starting artifact registration")

    db = get_database()

    try:
        # 获取已写章节
        written_sections = []
        for section_id in state.written_section_ids:
            # TODO: 从数据库获取章节内容
            pass

        # 组装最终综述
        final_review = "\n\n".join([s.get("content", "") for s in written_sections])

        # 计算统计信息
        word_count = len(final_review.split())
        citation_count = len(state.core_paper_ids) + len(state.auxiliary_paper_ids)

        # 保存产出物
        artifact_data = {
            "project_id": state.project_id,
            "final_review": final_review,
            "bibtex": state.bibtex,
            "word_count": word_count,
            "citation_count": citation_count,
        }
        artifact_id = await db.save_artifact(artifact_data)

        logger.info(
            "Artifact registration completed",
            artifact_id=artifact_id,
            word_count=word_count,
            citation_count=citation_count,
        )

        return {
            "artifact_id": artifact_id,
            "status": "artifacts_registered",
        }

    except Exception as e:
        logger.error("Artifact registration failed", error=str(e))
        return {
            "artifact_id": None,
            "status": "artifacts_registered",
            "errors": [f"Artifact registration failed: {str(e)}"],
        }
