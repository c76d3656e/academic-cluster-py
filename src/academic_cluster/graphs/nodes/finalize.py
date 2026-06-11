"""
终结节点 - 完成 Pipeline 运行，输出 review.md 和 references.bib
"""

import os

import structlog

from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()

# 输出目录
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "output")


async def finalize_node(state: PipelineState) -> dict:
    """
    终结 Pipeline

    - 输出 review.md 综述文件
    - 输出 references.bib 引用文件
    - 记录运行统计信息
    """
    logger.info(
        "Finalizing pipeline",
        project_id=state.project_id,
        query=state.query,
    )

    db = get_database()

    try:
        # 确保输出目录存在
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # 输出 review.md
        review_content = state.final_review or ""
        outline_data = state.outline_data or {}
        title = outline_data.get("title", f"Review: {state.query}")

        review_md = f"# {title}\n\n"
        review_md += f"**Project ID:** {state.project_id}\n\n"
        review_md += f"**Query:** {state.query}\n\n"
        review_md += f"**Papers analyzed:** {len(state.core_paper_ids)} core, {len(state.auxiliary_paper_ids)} auxiliary\n\n"
        review_md += "---\n\n"

        if review_content:
            review_md += review_content
        else:
            review_md += "*No review content generated.*\n"

        review_path = os.path.join(OUTPUT_DIR, f"review_{state.project_id[:8]}.md")
        with open(review_path, "w", encoding="utf-8") as f:
            f.write(review_md)
        logger.info("Review written", path=review_path)

        # 输出 references.bib
        bibtex_content = state.bibtex or ""
        bib_path = os.path.join(OUTPUT_DIR, f"references_{state.project_id[:8]}.bib")
        with open(bib_path, "w", encoding="utf-8") as f:
            f.write(bibtex_content)
        logger.info("BibTeX written", path=bib_path)

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
            "review_path": review_path,
            "bib_path": bib_path,
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
