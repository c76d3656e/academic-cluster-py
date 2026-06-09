"""
综述写作节点 - 生成综述内容
"""

import asyncio

import structlog

from ...agents.writing import write_section
from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def write_review_node(state: PipelineState) -> dict:
    """
    写作综述

    使用 LLM 生成综述内容：
    1. 获取大纲和章节计划
    2. 获取相关论文和证据卡片
    3. 并行写入各章节
    4. 组装综述
    5. 生成 BibTeX
    """
    logger.info("Starting review writing", outline_id=state.outline_id)

    db = get_database()

    try:
        # 获取大纲
        outline = None
        if state.outline_id:
            # TODO: 从数据库获取大纲详情
            pass

        # 获取核心论文详情
        papers = await db.get_papers_by_ids(state.core_paper_ids)

        # 获取证据卡片
        evidence_cards = []
        for card_id in state.evidence_card_ids:
            # TODO: 从数据库获取证据卡片详情
            pass

        # 构建论文上下文
        papers_context = "\n\n".join([
            f"[{i+1}] {p.get('title', '')}\n{p.get('abstract', '')}"
            for i, p in enumerate(papers[:50])
        ])

        # 获取章节计划
        sections = outline.get("sections", []) if outline else []

        # 并行写入各章节
        written_sections = []
        section_plan_ids = []
        citation_plan_ids = []
        written_section_ids = []

        for section in sections:
            try:
                content = await write_section(
                    section_plan=section,
                    papers_context=papers_context,
                )

                # 保存章节
                section_data = {
                    "section_plan_id": section.get("id"),
                    "content": content,
                    "word_count": len(content.split()),
                }
                section_id = await db.save_written_section(section_data)

                written_sections.append(content)
                written_section_ids.append(section_id)

            except Exception as e:
                logger.error("Section writing failed", section=section.get("title"), error=str(e))
                written_sections.append(f"[写作失败: {str(e)}]")

        # 组装综述
        final_review = "\n\n".join(written_sections)

        # 生成 BibTeX（简化版本）
        bibtex = _generate_bibtex(papers)

        # 保存产出物
        final_review_id = f"review_{state.project_id}"

        logger.info(
            "Review writing completed",
            sections=len(written_sections),
            total_words=len(final_review.split()),
        )

        return {
            "section_plan_ids": section_plan_ids,
            "citation_plan_ids": citation_plan_ids,
            "written_section_ids": written_section_ids,
            "final_review_id": final_review_id,
            "bibtex": bibtex,
            "status": "written",
        }

    except Exception as e:
        logger.error("Review writing failed", error=str(e))
        return {
            "section_plan_ids": [],
            "citation_plan_ids": [],
            "written_section_ids": [],
            "final_review_id": None,
            "bibtex": None,
            "status": "written",
            "errors": [f"Review writing failed: {str(e)}"],
        }


def _generate_bibtex(papers: list[dict]) -> str:
    """生成 BibTeX 引用"""
    entries = []

    for i, paper in enumerate(papers):
        # 提取作者
        authors = paper.get("authors", [])
        author_str = " and ".join([
            a.get("name", "Unknown") for a in authors[:3]
        ]) or "Unknown"

        # 提取年份
        year = paper.get("year", "2024")

        # 生成 key
        first_author = authors[0].get("name", "Unknown").split()[-1] if authors else "Unknown"
        key = f"{first_author}{year}_{i}"

        entry = f"""@article{{{key},
  title = {{{paper.get("title", "Untitled")}}},
  author = {{{author_str}}},
  year = {{{year}}},
  journal = {{{paper.get("journal", "Unknown")}}},
  doi = {{{paper.get("doi", "")}}},
}}"""
        entries.append(entry)

    return "\n\n".join(entries)
