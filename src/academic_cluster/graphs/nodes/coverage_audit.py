"""
覆盖审计节点 - 评估综述的引用覆盖率

对齐 Rust 版 citation_coverage.rs：
- 使用 citation_utils.validate_citations 进行引用校验
- 计算覆盖率、无效引用数、论文覆盖率
"""

import traceback

import structlog

from ...services.citation_utils import validate_citations
from ...services.database import get_database
from ...services.observability import get_current_tracker
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()


async def coverage_audit_node(state: PipelineState) -> dict:
    """
    覆盖审计

    评估综述的引用覆盖率：
    - 检查无效引用（引用了不存在的论文）
    - 计算引用覆盖率
    - 计算论文覆盖率
    - 决定是否需要修订
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("coverage_audit", "compute", index=8)

    logger.info("Starting coverage audit")

    await send_progress(
        state.project_id, "coverage_audit",
        "覆盖率审计中...",
    )

    db = get_database()

    try:
        # 获取已写章节
        written_sections = await db.get_written_sections_by_ids(state.written_section_ids)
        if not written_sections:
            raise ValueError("No written sections to audit - write_review must complete first")

        valid_paper_count = len(state.core_paper_ids)
        total_papers = valid_paper_count + len(state.auxiliary_paper_ids)

        # 使用 citation_utils 校验每个章节
        total_citations = 0
        total_valid = 0
        total_invalid = 0
        all_cited_indices = set()

        for section in written_sections:
            content = section.get("content", "")
            result = validate_citations(content, valid_paper_count)
            total_valid += result["valid_count"]
            total_invalid += result["invalid_count"]
            total_citations += result["valid_count"] + result["invalid_count"]

        # 计算覆盖率
        if total_citations > 0:
            coverage_score = total_valid / total_citations
        else:
            coverage_score = 0.0

        # 检查论文覆盖率（从 final_review 中统计）
        final_review = state.final_review or ""
        if final_review:
            import re
            cited_numbers = set()
            for match in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", final_review):
                for num_str in match.group(1).split(","):
                    try:
                        cited_numbers.add(int(num_str.strip()))
                    except ValueError:
                        pass
            all_cited_indices = cited_numbers

        paper_coverage = len(all_cited_indices) / max(total_papers, 1)

        needs_revision = total_invalid > 0

        logger.info(
            "Coverage audit completed",
            coverage=coverage_score,
            paper_coverage=paper_coverage,
            total_citations=total_citations,
            invalid_citations=total_invalid,
            cited_papers=len(all_cited_indices),
            total_papers=total_papers,
            needs_revision=needs_revision,
        )

        await send_progress(
            state.project_id, "coverage_audit",
            f"覆盖率审计完成，引用覆盖率 {coverage_score:.0%}，无效引用 {total_invalid} 个",
            detail={
                "coverage_score": coverage_score,
                "paper_coverage": paper_coverage,
                "invalid_citations": total_invalid,
                "needs_revision": needs_revision,
            },
        )

        result = {
            "coverage_score": coverage_score,
            "invalid_citation_count": total_invalid,
            "status": "audited",
        }
        if tracker:
            await tracker.end_node("coverage_audit", "succeeded", output_summary={
                "coverage_score": coverage_score,
                "invalid_citations": total_invalid,
            })
        return result

    except Exception as e:
        if tracker:
            await tracker.end_node("coverage_audit", "failed",
                                   error_message=str(e),
                                   error_traceback=traceback.format_exc())
        logger.error("Coverage audit failed", error=str(e))
        raise
