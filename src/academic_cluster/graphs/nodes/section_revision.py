"""
章节修订节点 - 修订无效引用

对齐 Rust 版 section_revision.rs：
1. 校验引用有效性（validate_citations）
2. 移除无效引用（strip_invalid_citations）
3. 重编号引用（renumber_citations_by_first_use）
4. 重新组装综述
"""

import traceback

import structlog

from ...services.citation_utils import (
    renumber_citations_by_first_use,
    render_reference_list,
    strip_invalid_citations,
    validate_citations,
)
from ...services.database import get_database
from ...services.observability import get_current_tracker
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()


async def section_revision_node(state: PipelineState) -> dict:
    """
    章节修订

    对齐 Rust 版 section_revision.rs 的确定性修订流程：
    1. 校验每个章节的引用有效性
    2. 移除无效引用编号（保留有效部分）
    3. 按首次出现顺序重编号
    4. 重新组装综述 + 参考文献列表
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("section_revision", "compute", index=9)

    logger.info("Starting section revision", invalid_citations=state.invalid_citation_count)

    await send_progress(
        state.project_id, "section_revision",
        f"章节修订中，处理 {state.invalid_citation_count} 个无效引用...",
    )

    db = get_database()

    try:
        valid_paper_count = len(state.core_paper_ids)

        # 获取已写章节
        written_sections = await db.get_written_sections_by_ids(state.written_section_ids)
        if not written_sections:
            raise ValueError("No written sections to revise")

        # 获取大纲（用于章节标题）
        outline = state.outline_data or {}
        sections_meta = outline.get("sections", [])

        # === Step 1: 校验 + 移除无效引用 ===
        all_invalid = set()
        revised_contents = []

        for i, section in enumerate(written_sections):
            content = section.get("content", "")

            # 校验引用
            result = validate_citations(content, valid_paper_count)
            if result["invalid_numbers"]:
                all_invalid.update(result["invalid_numbers"])
                logger.warning(
                    "Invalid citations in section",
                    section_index=i,
                    invalid=result["invalid_numbers"],
                    out_of_range=result["out_of_range"],
                )

            # 移除无效引用
            if result["invalid_numbers"]:
                content = strip_invalid_citations(content, set(result["invalid_numbers"]))

            revised_contents.append(content)

        # === Step 2: 按首次出现顺序重编号 ===
        # 构建 paper_metadata_map（original_number -> paper info）
        papers = await db.get_papers_by_ids(state.core_paper_ids)
        paper_metadata_map = {}
        for i, p in enumerate(papers):
            authors = p.get("authors", [])
            author_str = ", ".join(a.get("name", "Unknown") for a in authors[:3])
            if len(authors) > 3:
                author_str += " et al."
            paper_metadata_map[i + 1] = {
                "paper_id": p.get("id", ""),
                "title": p.get("title", ""),
                "authors": author_str,
                "venue": p.get("journal", p.get("venue", "")),
                "year": str(p.get("year", "")),
                "doi": p.get("doi", ""),
            }

        # 拼接各章节（带标题）
        review_parts = []
        for i, content in enumerate(revised_contents):
            title = ""
            if i < len(sections_meta):
                title = sections_meta[i].get("title", "")
            if title:
                review_parts.append(f"## {title}\n\n{content}")
            else:
                review_parts.append(content)
        assembled = "\n\n".join(review_parts)

        # 重编号
        final_review, ref_mappings = renumber_citations_by_first_use(
            assembled, paper_metadata_map
        )

        # 生成参考文献列表
        ref_list = render_reference_list(papers, ref_mappings)
        final_review = final_review.rstrip() + "\n\n## References\n\n" + ref_list

        # 更新章节到数据库
        for i, section in enumerate(written_sections):
            section_id = section.get("id")
            if section_id and i < len(revised_contents):
                await db.save_written_section({
                    "id": section_id,
                    "outline_id": section.get("outline_id"),
                    "section_id": section.get("section_id"),
                    "content": revised_contents[i],
                    "word_count": len(revised_contents[i]),
                })

        logger.info(
            "Section revision completed",
            sections_revised=len(revised_contents),
            invalid_stripped=len(all_invalid),
            final_references=len(ref_mappings),
            total_chars=len(final_review),
        )

        await send_progress(
            state.project_id, "section_revision",
            f"章节修订完成，移除 {len(all_invalid)} 个无效引用",
        )

        result = {
            "final_review": final_review,
            "invalid_citation_count": len(all_invalid),
            "status": "revised",
        }
        if tracker:
            await tracker.end_node("section_revision", "succeeded", output_summary={
                "sections_revised": len(revised_contents),
                "invalid_stripped": len(all_invalid),
            })
        return result

    except Exception as e:
        if tracker:
            await tracker.end_node("section_revision", "failed",
                                   error_message=str(e),
                                   error_traceback=traceback.format_exc())
        logger.error("Section revision failed", error=str(e))
        raise
