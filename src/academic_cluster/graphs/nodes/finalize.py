"""
终结节点 - 完成 Pipeline 运行
"""

import structlog

from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def finalize_node(state: PipelineState) -> dict:
    """
    终结 Pipeline

    - 更新项目状态为完成
    - 记录运行统计信息
    - 清理临时数据
    """
    logger.info(
        "Finalizing pipeline",
        project_id=state.project_id,
        query=state.query,
    )

    db = get_database()

    try:
        # 更新项目状态
        # TODO: 更新数据库中的项目状态

        # 计算统计信息
        stats = {
            "total_papers_searched": state.total_searched,
            "papers_after_filter": len(state.paper_ids),
            "core_papers": len(state.core_paper_ids),
            "auxiliary_papers": len(state.auxiliary_paper_ids),
            "clusters": len(state.cluster_ids),
            "evidence_cards": len(state.evidence_card_ids),
            "sections_written": len(state.written_section_ids),
            "refinement_attempts": state.refinement_attempt,
        }

        logger.info("Pipeline completed successfully", stats=stats)

        return {
            "status": "completed",
        }

    except Exception as e:
        logger.error("Finalization failed", error=str(e))
        return {
            "status": "completed",
            "errors": [f"Finalization failed: {str(e)}"],
        }
