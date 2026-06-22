"""
产出物注册节点 - 生成最终产出物
"""

from typing import Any

import structlog

from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def artifact_registration_node(state: PipelineState) -> dict[str, Any]:
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
        # 使用 state 中的最终综述内容
        final_review = state.final_review

        if not final_review:
            raise ValueError(
                "No final review content - write_review must complete first"
            )

        # 计算统计信息
        word_count = len(final_review.split())
        citation_count = len(state.core_paper_ids) + len(state.auxiliary_paper_ids)

        # 保存产出物
        artifact_data = {
            "project_id": state.project_id,
            "final_review": final_review,
            "abstract": state.abstract,
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
        raise  # 不再 fallback，直接抛出异常
