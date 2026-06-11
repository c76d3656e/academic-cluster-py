"""
综述写作节点 - 生成综述内容

对齐 Rust 版 review_writer 的完整流程：
1. 大纲 → 引用规划（per-section citation allocation）
2. 逐章写作（带证据卡片和分配的引用）
3. 引用校验 → 修订 → 重编号
4. 确定性组装
"""

import structlog

from ...agents.writing import write_section
from ...services.citation_planner import plan_review_citations, render_section_references
from ...services.citation_utils import (
    renumber_citations_by_first_use,
    render_reference_list,
    strip_reference_block,
    validate_citations,
)
from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def write_review_node(state: PipelineState) -> dict:
    """
    写作综述

    对齐 Rust 版 review_writer 流程：
    1. 引用规划：为每个章节分配候选参考文献
    2. 逐章写作：每章只拿到分配的引用 + 证据卡片
    3. 引用校验 + 修订
    4. 重编号 + 确定性组装
    """
    logger.info("Starting review writing", outline_id=state.outline_id)

    db = get_database()

    try:
        outline = state.outline_data
        # 断点恢复时 outline_data 可能为空，从 DB 回退加载
        if not outline:
            logger.info("outline_data missing in state, loading from DB", project_id=state.project_id)
            outline = await db.get_outline_by_project_id(state.project_id)
        if not outline:
            raise ValueError("No outline data available - outline_generation must complete first")

        review_title = outline.get("title", "综述")
        sections = outline.get("sections", [])
        if not sections:
            raise ValueError("Outline has no sections")

        # 获取核心论文详情
        papers = await db.get_papers_by_ids(state.core_paper_ids)
        if not papers:
            raise ValueError("No core papers available for writing")

        # 获取聚类数据
        clusters = []
        if state.cluster_ids:
            clusters = await db.get_clusters_by_ids(state.cluster_ids)

        # 获取证据卡片
        evidence_cards = []
        if state.evidence_card_ids:
            evidence_cards = await db.get_evidence_cards_by_ids(state.evidence_card_ids)

        # 构建 paper_id -> paper 映射
        paper_map = {p["id"]: p for p in papers}

        # === Step 1: 引用规划（对齐 Rust 版 citation_planner） ===
        citation_plans = plan_review_citations(
            sections=sections,
            papers=papers,
            clusters=clusters,
            section_reference_target=30,
        )

        # 构建 paper_id -> 论文元数据映射（用于后续重编号）
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

        # 构建 evidence_cards 按 paper_id 索引
        ec_by_paper = {}
        for card in evidence_cards:
            pid = card.get("paper_id", "")
            if pid:
                ec_by_paper.setdefault(pid, []).append(card)

        logger.info(
            "Citation planning completed",
            sections=len(citation_plans),
            total_papers=len(papers),
        )

        # === Step 2: 逐章写作（支持幂等恢复） ===
        # 查询已写章节，跳过
        existing_sections = {}  # section_id -> {content, id}
        if state.outline_id:
            try:
                async with db.session() as session:
                    from sqlalchemy import text
                    result = await session.execute(
                        text("SELECT id, section_id, content FROM written_content WHERE outline_id = :oid"),
                        {"oid": state.outline_id}
                    )
                    for row in result.fetchall():
                        existing_sections[str(row[1])] = {
                            "id": str(row[0]),
                            "content": str(row[2]),
                        }
                if existing_sections:
                    logger.info(
                        "Resuming write_review, skipping already written sections",
                        existing_count=len(existing_sections),
                        total_sections=len(citation_plans),
                    )
            except Exception as e:
                logger.warning("Failed to check existing sections", error=str(e))

        written_sections = []
        written_section_ids = []

        for plan in citation_plans:
            si = plan.section_index
            section = sections[si]
            section_id_key = str(section.get("name", section.get("number", 0)))

            # 幂等：跳过已写章节
            if section_id_key in existing_sections:
                existing = existing_sections[section_id_key]
                written_sections.append(existing["content"])
                written_section_ids.append(existing["id"])
                logger.info("Skipping already written section", title=section.get("title"))
                continue

            # 渲染该章节分配的参考文献（局部编号 1..N）
            section_refs = render_section_references(plan, paper_map)

            # 该章节的证据卡片
            section_evidence = []
            for pid in plan.candidate_paper_ids[:10]:
                section_evidence.extend(ec_by_paper.get(pid, []))

            # 构建聚类数据上下文
            cluster_data_parts = []
            # 构建聚类查找表（支持按 id 查找和按索引查找）
            cluster_map = {str(c.get("id", "")): c for c in clusters}
            for ci in plan.key_clusters:
                c = None
                # ci 可能是整数索引或 UUID 字符串
                if isinstance(ci, int) and 0 <= ci < len(clusters):
                    c = clusters[ci]
                elif isinstance(ci, str):
                    c = cluster_map.get(ci)
                if c:
                    cluster_data_parts.append(
                        f"Cluster {c.get('id', ci)}: {c.get('size', 0)} papers, "
                        f"theme: {c.get('theme', c.get('description', 'N/A'))}"
                    )

            # 构建论文样本上下文
            sample_parts = []
            for pid in plan.candidate_paper_ids[:10]:
                p = paper_map.get(pid)
                if p:
                    abstract = (p.get("abstract") or "")[:200]
                    sample_parts.append(f"- {p.get('title', '')}: {abstract}")

            content = await write_section(
                topic=state.query,
                review_title=review_title,
                section_plan=section,
                cluster_data="\n".join(cluster_data_parts) or "暂无聚类数据",
                sample_papers="\n".join(sample_parts) or "暂无论文样本",
                references=section_refs,
                evidence_cards=section_evidence,
            )

            # LLM 响应 content 可能是 list（多模态格式）或 string
            if isinstance(content, list):
                content = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )

            if not content or len(content.strip()) < 50:
                raise ValueError(f"Section '{section.get('title')}' produced insufficient content")

            # 保存章节
            section_data = {
                "outline_id": state.outline_id,
                "section_id": str(section.get("name", section.get("number", 0))),
                "content": content,
                "word_count": len(content),
            }
            section_id = await db.save_written_section(section_data)

            written_sections.append(content)
            written_section_ids.append(section_id)

            logger.info(
                "Section written",
                title=section.get("title"),
                word_count=section_data["word_count"],
                refs=len(plan.candidate_paper_ids),
            )

        # === Step 3: 引用校验 + 修订 ===
        valid_paper_count = len(papers)
        all_invalid = set()

        try:
            for i, content in enumerate(written_sections):
                result = validate_citations(content, valid_paper_count)
                if result["invalid_numbers"]:
                    all_invalid.update(result["invalid_numbers"])
                    logger.warning(
                        "Invalid citations found",
                        section=i,
                        invalid=result["invalid_numbers"],
                    )
        except Exception as e:
            logger.error("Citation validation failed", error=str(e), step="validate_citations")
            raise

        # 如果有无效引用，从所有章节中移除
        if all_invalid:
            try:
                from ...services.citation_utils import strip_invalid_citations
                revised = []
                for content in written_sections:
                    revised.append(strip_invalid_citations(content, all_invalid))
                written_sections = revised
                logger.info("Stripped invalid citations", count=len(all_invalid))
            except Exception as e:
                logger.error("Strip invalid citations failed", error=str(e), step="strip_invalid")
                raise

        # === Step 4: 重编号 + 组装 ===
        try:
            # 先拼接各章节（带章节标题）
            review_parts = []
            for i, section in enumerate(sections):
                title = section.get("title", "")
                if i < len(written_sections) and written_sections[i]:
                    if title:
                        review_parts.append(f"## {title}\n\n{written_sections[i]}")
                    else:
                        review_parts.append(written_sections[i])
            assembled_review = "\n\n".join(review_parts)

            # 去掉已有的参考文献块
            assembled_review = strip_reference_block(assembled_review)
            logger.info("Step 4a: assembled review", length=len(assembled_review))
        except Exception as e:
            logger.error("Assembly failed", error=str(e), step="assembly")
            raise

        try:
            # 按首次出现顺序重编号
            final_review, ref_mappings = renumber_citations_by_first_use(
                assembled_review, paper_metadata_map
            )
            logger.info("Step 4b: renumbered citations", mappings=len(ref_mappings))
        except Exception as e:
            logger.error("Renumber failed", error=str(e), step="renumber",
                        paper_map_keys=list(paper_metadata_map.keys())[:10])
            raise

        try:
            # 生成参考文献列表
            ref_list = render_reference_list(papers, ref_mappings)
            final_review = final_review.rstrip() + "\n\n## References\n\n" + ref_list
            logger.info("Step 4c: rendered reference list")
        except Exception as e:
            logger.error("Render reference list failed", error=str(e), step="render_refs")
            raise

        # 生成 BibTeX
        bibtex = _generate_bibtex(papers)

        final_review_id = f"review_{state.project_id}"

        logger.info(
            "Review writing completed",
            sections=len(written_sections),
            total_chars=len(final_review),
            references=len(ref_mappings),
        )

        return {
            "written_section_ids": written_section_ids,
            "final_review_id": final_review_id,
            "final_review": final_review,
            "bibtex": bibtex,
            "status": "written",
        }

    except Exception as e:
        import traceback
        logger.error("Review writing failed", error=str(e), traceback=traceback.format_exc())
        raise


def _generate_bibtex(papers: list[dict]) -> str:
    """生成 BibTeX 引用"""
    entries = []
    for i, paper in enumerate(papers):
        authors = paper.get("authors", [])
        author_str = " and ".join(
            a.get("name", "Unknown") for a in authors[:3]
        ) or "Unknown"
        year = paper.get("year") or "2024"
        first_author = authors[0].get("name", "Unknown").split()[-1] if authors else "Unknown"
        key = f"{first_author}{year}_{i}"
        journal = paper.get("journal") or paper.get("venue") or ""
        doi = paper.get("doi") or ""
        entry = f"""@article{{{key},
  title = {{{paper.get("title", "Untitled")}}},
  author = {{{author_str}}},
  year = {{{year}}},
  journal = {{{journal}}},
  doi = {{{doi}}},
}}"""
        entries.append(entry)
    return "\n\n".join(entries)
