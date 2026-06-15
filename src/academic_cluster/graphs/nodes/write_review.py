"""
综述写作节点 - 生成综述内容

对齐 Rust 版 review_writer 的完整流程：
1. 大纲 → 引用规划（per-section citation allocation）
2. 逐章写作（带证据卡片和分配的引用）
3. 引用校验 → 修订 → 重编号
4. 确定性组装
"""

import traceback
from dataclasses import asdict

import structlog

from ...agents.writing import (
    render_section_community_context,
    render_section_evidence_limitations,
    write_section_units,
)
from ...agents.section_outline import plan_section_outline
from ...agents.section_evaluator import evaluate_section, revise_section
from ...services.citation_planner import plan_review_citations, render_section_references
from ...services.citation_utils import (
    clean_filler_phrases,
    is_primarily_chinese,
    replace_uuid_citations,
    normalize_citation_surface,
    strip_author_year_citations,
    strip_body_structure_leakage,
    strip_meta_commentary,
    strip_prompt_leakage,
    strip_revision_commentary,
    strip_section_reference_block,
    strip_unsupported_precise_metrics,
    validate_citations,
)
from ...services.citation_support import audit_citation_support
from ...services.coverage_audit import audit_citation_coverage, route_after_coverage_audit
from ...services.database import get_database
from ...services.observability import get_current_tracker
from ...services.review_finalizer import finalize_review_markdown, remap_section_local_citations
from ...services.section_evidence_planner import (
    cards_from_support_matrix,
    plan_section_evidence,
)
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()


def _split_finalized_body_by_section(body_markdown: str, sections: list[dict]) -> list[str]:
    """Split finalized review body back into section bodies for UI storage."""
    if not body_markdown or not sections:
        return []

    lines = body_markdown.splitlines()
    chunks: list[list[str]] = []
    current: list[str] | None = None
    expected_titles = {
        str(section.get("title") or "").strip()
        for section in sections
        if section.get("title")
    }

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("# "):
            continue
        if stripped.startswith("## "):
            title = stripped[3:].strip()
            if title in expected_titles:
                if current is not None:
                    chunks.append(current)
                current = []
                continue
        if current is not None:
            current.append(line)

    if current is not None:
        chunks.append(current)

    return ["\n".join(chunk).strip() for chunk in chunks]


def _paper_id_to_global_number(papers: list[dict]) -> dict[str, int]:
    return {
        str(p.get("id")): idx + 1
        for idx, p in enumerate(papers)
        if p.get("id")
    }


def _paper_year(paper: dict) -> str:
    year = paper.get("year")
    if year:
        return str(year)
    publication_date = paper.get("publication_date")
    if publication_date:
        return str(publication_date)[:4]
    return ""


def _section_citation_payload(plan, paper_map: dict[str, dict]) -> dict:
    details_by_id = {
        detail.get("paper_id"): detail
        for detail in getattr(plan, "candidate_details", [])
        if detail.get("paper_id")
    }
    papers = []
    for local_number, paper_id in enumerate(plan.candidate_paper_ids, 1):
        paper = paper_map.get(paper_id, {})
        detail = details_by_id.get(paper_id, {})
        papers.append({
            "local_number": local_number,
            "id": paper_id,
            "paper_id": paper_id,
            "title": paper.get("title", ""),
            "abstract": paper.get("abstract", ""),
            "authors": paper.get("authors", []),
            "year": _paper_year(paper),
            "venue": paper.get("journal", paper.get("venue", "")),
            "cluster_id": detail.get("cluster_id"),
            "source": detail.get("source", "unknown"),
            "is_core": detail.get("is_core", False),
        })

    return {
        **asdict(plan),
        "papers": papers,
    }


async def write_review_node(state: PipelineState) -> dict:
    """
    写作综述

    对齐 Rust 版 review_writer 流程：
    1. 引用规划：为每个章节分配候选参考文献
    2. 逐章写作：每章只拿到分配的引用 + 证据卡片
    3. 引用校验 + 修订
    4. 重编号 + 确定性组装
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("write_review", "llm", index=5)

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
        review_paper_ids = list(dict.fromkeys(
            list(state.core_paper_ids or []) + list(state.auxiliary_paper_ids or [])
        ))
        papers = await db.get_papers_by_ids(review_paper_ids or state.core_paper_ids)
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

        # 获取混合图边（用于跨聚类邻居发现）
        hybrid_edges = []
        try:
            from ...services.vector_store import get_vector_store
            vector_store = get_vector_store()
            all_paper_ids = state.reranked_paper_ids or state.core_paper_ids
            hybrid_edges = await vector_store.get_knn_graph(
                paper_ids=all_paper_ids, k=10, threshold=0.3
            )
        except Exception as e:
            logger.warning("Failed to load hybrid edges for citation planning", error=str(e))

        # === Step 1: 引用规划（对齐 Rust 版 citation_planner，8 层优先级） ===
        config = state.config or {}
        core_count = config.get("core_reference_count", 160)
        citation_plans = plan_review_citations(
            sections=sections,
            papers=papers,
            clusters=clusters,
            section_reference_target=30,
            hybrid_edges=hybrid_edges,
            core_reference_count=core_count,
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
                "year": _paper_year(p),
                "doi": p.get("doi", ""),
            }

        # 构建 evidence_cards 按 paper_id 索引
        ec_by_paper = {}
        for card in evidence_cards:
            pid = card.get("paper_id", "")
            if pid:
                ec_by_paper.setdefault(pid, []).append(card)

        community_memories = []
        try:
            if state.community_memory_ids:
                community_memories = await db.get_community_memories_by_ids(state.community_memory_ids)
            if not community_memories:
                community_memories = await db.get_community_memories_by_project(state.project_id)
        except Exception as e:
            logger.warning("Failed to load community memories for evidence planning", error=str(e))

        # 获取 KG 实体（用于社区上下文的 top_entities）
        kg_entities = []
        if state.kg_entity_ids:
            try:
                kg_entities = await db.get_kg_entities_by_ids(state.kg_entity_ids)
            except Exception:
                pass

        logger.info(
            "Citation planning completed",
            sections=len(citation_plans),
            total_papers=len(papers),
        )

        citation_plans, section_evidence_plans = plan_section_evidence(
            topic=state.query,
            sections=sections,
            citation_plans=citation_plans,
            evidence_cards=evidence_cards,
            community_memories=community_memories,
            paper_map=paper_map,
            clusters=clusters,
            max_references_per_section=int(config.get("section_reference_target", 18)),
            min_references_per_section=int(config.get("section_reference_min", 8)),
        )
        logger.info(
            "Section evidence planning completed",
            sections=len(section_evidence_plans),
            total_candidates=sum(len(p.candidate_paper_ids) for p in citation_plans),
        )

        # 获取 KG 关系（用于 section outline）
        kg_relations = []
        if state.kg_relation_ids:
            try:
                kg_relations = await db.get_kg_relations_by_ids(state.kg_relation_ids)
            except Exception:
                pass

        # === Step 2: 逐章写作（支持幂等恢复，含 section outline + evaluation） ===
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
        written_outlines = []  # 追踪每个 section 的 outline 规划（用于上下文链）

        total_sections = len(citation_plans)
        for plan_idx, plan in enumerate(citation_plans):
            si = plan.section_index
            section = sections[si]
            section_id_key = str(section.get("name", section.get("number", 0)))

            # 幂等：跳过已写章节
            if section_id_key in existing_sections:
                existing = existing_sections[section_id_key]
                written_sections.append(existing["content"])
                written_section_ids.append(existing["id"])
                written_outlines.append(None)  # 恢复时无 outline 信息
                logger.info("Skipping already written section", title=section.get("title"))
                continue

            section_title = section.get("title", f"章节 {plan_idx + 1}")
            await send_progress(
                state.project_id, "write_review",
                f"正在规划第 {plan_idx + 1}/{total_sections} 章节: {section_title}",
                progress=(plan_idx + 1) / total_sections * 0.3,
            )

            # === Step 2a: Section Outline Planning ===
            prev_outline = written_outlines[-1] if written_outlines else None
            next_section = sections[si + 1] if si + 1 < len(sections) else None

            # 该章节的证据卡片
            section_evidence_plan = section_evidence_plans.get(si, {})
            section_evidence = cards_from_support_matrix(
                section_evidence_plan.get("support_matrix") or []
            )
            if not section_evidence:
                for pid in plan.candidate_paper_ids[:10]:
                    section_evidence.extend(ec_by_paper.get(pid, []))

            section_outline = await plan_section_outline(
                section_plan=section,
                citation_plan=_section_citation_payload(plan, paper_map),
                prev_outline=prev_outline,
                next_section=next_section,
                clusters=clusters,
                evidence_cards=section_evidence,
                kg_entities=kg_entities,
                kg_relations=kg_relations,
            )
            written_outlines.append(section_outline)

            logger.info(
                "Section outline planned",
                title=section_title,
                paragraphs=len(section_outline.get("paragraphs", [])),
                core_question=section_outline.get("core_question", "")[:80],
            )

            # === Step 2b: Write Section（注入段落规划 + 上下文链） ===
            await send_progress(
                state.project_id, "write_review",
                f"正在撰写第 {plan_idx + 1}/{total_sections} 章节: {section_title}",
                progress=(plan_idx + 1) / total_sections * 0.6,
            )

            # 渲染该章节分配的参考文献（局部编号 1..N）
            section_refs = render_section_references(plan, paper_map)

            # 构建聚类数据上下文
            cluster_data_parts = []
            key_clusters_str = ", ".join(str(c) for c in plan.key_clusters) if plan.key_clusters else "all available clusters"
            cluster_data_parts.append(
                f"section: {section.get('title', '')}\n"
                f"section_name: {section.get('name', 'unnamed')}\n"
                f"key_clusters: {key_clusters_str}"
            )

            citation_plan_summary = _render_citation_plan_summary(plan, paper_map)
            if citation_plan_summary:
                cluster_data_parts.append(citation_plan_summary)

            support_matrix = section_evidence_plan.get("support_matrix") or []
            if support_matrix:
                matrix_lines = ["section_evidence_support_matrix:"]
                for item in support_matrix[:18]:
                    matrix_lines.append(
                        f"- paper_id={item.get('paper_id')}; score={item.get('relevance_score')}; "
                        f"source={item.get('candidate_source')}; claim={item.get('claim', '')[:180]}"
                    )
                cluster_data_parts.append("\n".join(matrix_lines))

            # 全局聚类统计
            paper_to_cluster = {}
            for c in clusters:
                for pid in c.get("paper_ids") or []:
                    paper_to_cluster[pid] = c.get("id")
            entity_by_paper_cluster: dict[str, list[str]] = {}
            for ent in kg_entities:
                for pid in ent.get("paper_ids") or []:
                    entity_by_paper_cluster.setdefault(pid, []).append(ent.get("name", ""))
            cluster_stats_parts = []
            for c in clusters:
                cid = c.get("id")
                c_papers = c.get("paper_ids") or []
                c_size = len(c_papers)
                entities = []
                for pid in c_papers[:50]:
                    entities.extend(entity_by_paper_cluster.get(pid, []))
                unique_entities = list(dict.fromkeys(entities))[:12]
                entity_str = ", ".join(unique_entities) if unique_entities else ""
                line = f"cluster {cid}: {c_size} papers"
                if entity_str:
                    line += f"; entities: {entity_str}"
                cluster_stats_parts.append(line)
            if cluster_stats_parts:
                cluster_data_parts.append("\n".join(cluster_stats_parts))

            # 构建论文样本上下文
            sample_parts = []
            for idx, pid in enumerate(plan.candidate_paper_ids[:30], 1):
                p = paper_map.get(pid)
                if not p:
                    continue
                card = ec_by_paper.get(pid, [None])[0] if ec_by_paper else None
                if card:
                    method = card.get("method", "unknown") or "unknown"
                    metric = card.get("metric", "none")
                    if isinstance(metric, dict):
                        import json as _json
                        metric = _json.dumps(metric)
                    elif not metric:
                        metric = "none"
                    limitation = card.get("limitation", "none") or "none"
                    confidence = card.get("confidence", 0.0)
                    sample_parts.append(
                        f"[{idx}] paper_id: {pid}\n"
                        f"title: {p.get('title', '')}\n"
                        f"evidence_card_id: evidence_card:{pid}\n"
                        f"claim: {card.get('claim', '')}\n"
                        f"evidence_span: {card.get('evidence_span', '')[:200]}\n"
                        f"method: {method}\n"
                        f"metric: {metric}\n"
                        f"limitation: {limitation}\n"
                        f"confidence: {confidence:.2f}"
                    )
                else:
                    abstract = (p.get("abstract") or "")[:300]
                    sample_parts.append(
                        f"[{idx}] paper_id: {pid}\n"
                        f"title: {p.get('title', '')}\n"
                        f"evidence_card_id: unavailable\n"
                        f"abstract: {abstract}"
                    )

            # 渲染社区上下文和证据局限性
            community_context = section_evidence_plan.get("community_context") or render_section_community_context(
                section_plan=section,
                clusters=clusters,
                papers=papers,
                evidence_cards=evidence_cards,
                kg_entities=kg_entities,
            )
            evidence_limitations = section_evidence_plan.get("evidence_limitations") or render_section_evidence_limitations(
                section_plan=section,
                evidence_cards=evidence_cards,
            )

            # 构建前序摘要（用于上下文链）
            prev_summary = ""
            if written_sections:
                prev_summaries = []
                for wo in written_outlines[:-1]:
                    if wo:
                        prev_summaries.append(
                            f"- {wo.get('core_question', '')}: {wo.get('narrative_arc', '')}"
                        )
                if prev_summaries:
                    prev_summary = "前序章节已覆盖的内容（不要重复）:\n" + "\n".join(prev_summaries)

            content = await write_section_units(
                topic=state.query,
                review_title=review_title,
                section_plan=section,
                cluster_data="\n".join(cluster_data_parts) or "暂无聚类数据",
                sample_papers="\n".join(sample_parts) or "暂无论文样本",
                references=section_refs,
                evidence_cards=section_evidence,
                community_context=community_context or None,
                evidence_limitations=evidence_limitations or None,
                section_outline=section_outline,
                prev_summary=prev_summary,
                next_outline=next_section,
            )

            # LLM 响应 content 可能是 list（多模态格式）或 string
            if isinstance(content, list):
                content = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )

            if not content or len(content.strip()) < 50:
                raise ValueError(f"Section '{section.get('title')}' produced insufficient content")

            # === 后处理：剥离章节内参考文献块 + 清理禁用词汇 ===
            content = strip_section_reference_block(content)
            content = clean_filler_phrases(content)
            content = strip_meta_commentary(content)
            content = strip_prompt_leakage(content)
            content = strip_revision_commentary(content)
            content = strip_body_structure_leakage(content)
            content = strip_author_year_citations(content)
            content = strip_unsupported_precise_metrics(content, section_evidence)
            content = normalize_citation_surface(content)

            # 替换 LLM 可能输出的 UUID 引用为正确编号
            paper_id_to_num = {
                d["paper_id"]: i + 1
                for i, d in enumerate(plan.candidate_details)
                if d.get("paper_id")
            }
            content = replace_uuid_citations(content, paper_id_to_num)

            # 语言检测
            if not is_primarily_chinese(content):
                logger.warning(
                    "Section primarily in non-Chinese language, content may need review",
                    title=section.get("title"),
                )

            # 字数异常检测
            target_chars = section.get("target_words", 2000) * 2
            if len(content) > target_chars * 2:
                logger.warning(
                    "Section overly long, truncating",
                    title=section.get("title"),
                    actual_chars=len(content),
                    target_chars=target_chars,
                )
                max_chars = int(target_chars * 1.8)
                truncated = content[:max_chars]
                last_para = truncated.rfind("\n\n")
                if last_para > max_chars * 0.6:
                    content = truncated[:last_para]
                logger.info("Truncated section", new_chars=len(content))

            # === Step 2c: Evaluate + Revise ===
            await send_progress(
                state.project_id, "write_review",
                f"正在评估第 {plan_idx + 1}/{total_sections} 章节: {section_title}",
                progress=(plan_idx + 1) / total_sections * 0.9,
            )

            next_outline_data = None
            if next_section:
                next_outline_data = {
                    "title": next_section.get("title", ""),
                    "description": next_section.get("description", ""),
                }

            evaluation = await evaluate_section(
                section_title=section_title,
                section_draft=content,
                section_outline=section_outline,
                target_words=section.get("target_words", 2000),
                prev_summary=prev_summary,
                next_outline=next_outline_data,
                references=section_refs,
            )

            logger.info(
                "Section evaluated",
                title=section_title,
                score=evaluation.get("score", 0),
                blind_score=evaluation.get("blind_evaluation", {}).get("score", 0),
                visible_score=evaluation.get("visible_evaluation", {}).get("score", 0),
                needs_revision=evaluation.get("needs_revision", False),
            )

            # 一轮修订（最多 1 轮，避免无限循环）
            if evaluation.get("needs_revision", False) and evaluation.get("score", 100) < 75:
                logger.info("Revising section based on evaluation feedback",
                            title=section_title,
                            instructions=evaluation.get("revision_instructions", "")[:100])
                content = await revise_section(
                    section_draft=content,
                    revision_instructions=evaluation.get("revision_instructions", ""),
                    section_outline=section_outline,
                    references=section_refs,
                )
                # 重新后处理
                content = strip_section_reference_block(content)
                content = clean_filler_phrases(content)
                content = strip_meta_commentary(content)
                content = strip_prompt_leakage(content)
                content = strip_revision_commentary(content)
                content = strip_body_structure_leakage(content)
                content = strip_author_year_citations(content)
                content = strip_unsupported_precise_metrics(content, section_evidence)
                content = normalize_citation_surface(content)

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

            # === Step 2d: Citation Support Audit（确定性引用支撑检测） ===
            section_evidence_for_audit = []
            for pid in plan.candidate_paper_ids[:30]:
                card_list = ec_by_paper.get(pid, [])
                if card_list:
                    section_evidence_for_audit.append(card_list[0])
                else:
                    section_evidence_for_audit.append({})

            support_result = audit_citation_support(
                section_text=content,
                evidence_cards=section_evidence_for_audit,
            )
            if support_result["unsupported_count"] > 0:
                logger.warning(
                    "Citation support audit found unsupported citations",
                    title=section_title,
                    supported=support_result["supported_count"],
                    weak=support_result["weak_count"],
                    unsupported=support_result["unsupported_count"],
                    support_rate=f"{support_result['support_rate']:.1%}",
                )

            logger.info(
                "Section written",
                title=section.get("title"),
                word_count=section_data["word_count"],
                refs=len(plan.candidate_paper_ids),
                evaluation_score=evaluation.get("score", 0),
                citation_support_rate=f"{support_result['support_rate']:.1%}",
            )

        await send_progress(
            state.project_id, "write_review",
            f"章节撰写完成，共 {len(written_sections)} 章，正在校验引用...",
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

        # 如果有无效引用，从所有章节中移除（对齐 Rust 版 deterministic_remove_invalid_citation_numbers）
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
            remapped_section_bodies: list[str] = []
            global_ref_map = _paper_id_to_global_number(papers)
            for idx, plan in enumerate(citation_plans):
                body = written_sections[idx] if idx < len(written_sections) else ""
                remapped_body, invalid_local = remap_section_local_citations(
                    body,
                    list(plan.candidate_paper_ids),
                    global_ref_map,
                )
                if invalid_local:
                    raise ValueError(
                        f"Section {idx} contains invalid local citations: {sorted(invalid_local)}"
                    )
                remapped_section_bodies.append(remapped_body)

            finalization = finalize_review_markdown(
                review_title=review_title,
                sections=sections,
                section_bodies=remapped_section_bodies,
                paper_metadata_map=paper_metadata_map,
            )
            displayed_section_bodies = _split_finalized_body_by_section(
                finalization.body_markdown,
                sections,
            )
            if len(displayed_section_bodies) == len(written_section_ids):
                for idx, section_id in enumerate(written_section_ids):
                    await db.save_written_section({
                        "id": section_id,
                        "outline_id": state.outline_id,
                        "section_id": str(sections[idx].get("name", sections[idx].get("number", idx))),
                        "content": displayed_section_bodies[idx],
                        "word_count": len(displayed_section_bodies[idx]),
                    })
            assembled_review = finalization.body_markdown
            final_review = finalization.markdown
            ref_mappings = finalization.reference_mappings
            await db.save_pipeline_checkpoint({
                "project_id": state.project_id,
                "node_name": "final_review_artifact",
                "state_snapshot": {
                    "final_review": final_review,
                    "body_markdown": finalization.body_markdown,
                    "references": ref_mappings,
                    "assembly_report": asdict(finalization.assembly_report),
                },
                "status": "completed",
            })
            logger.info(
                "Step 4a: deterministic assembly completed",
                length=len(assembled_review),
                mappings=len(ref_mappings),
            )
        except Exception as e:
            logger.error("Finalization failed", error=str(e), step="finalization")
            raise

        try:
            from ...services.citation_utils import _CITATION_RE, _YEAR_BRACKET_RE, parse_citation_numbers

            section_citations: list[set[int]] = []
            for body in remapped_section_bodies:
                cited_nums: set[int] = set()
                for match in _CITATION_RE.finditer(body):
                    if _YEAR_BRACKET_RE.fullmatch(match.group(0)):
                        continue
                    cited_nums.update(parse_citation_numbers(match.group(1)))
                section_citations.append(cited_nums)

            cited_paper_ids: set[str] = set()
            global_number_to_paper = {idx + 1: paper.get("id", "") for idx, paper in enumerate(papers)}
            for body in remapped_section_bodies:
                for match in _CITATION_RE.finditer(body):
                    if _YEAR_BRACKET_RE.fullmatch(match.group(0)):
                        continue
                    for number in parse_citation_numbers(match.group(1)):
                        paper_id = global_number_to_paper.get(number)
                        if paper_id:
                            cited_paper_ids.add(paper_id)

            cluster_paper_map = {
                str(c.get("id", "")): c.get("paper_ids", [])
                for c in clusters
            }
            planned_candidate_ids = list(dict.fromkeys(
                pid
                for plan in citation_plans
                for pid in plan.candidate_paper_ids
            ))
            final_validation = validate_citations(
                finalization.body_markdown,
                len(ref_mappings),
            )
            coverage_result = audit_citation_coverage(
                section_citations=section_citations,
                candidate_plans=[list(cp.candidate_paper_ids) for cp in citation_plans],
                cluster_paper_map=cluster_paper_map,
                cited_paper_ids=cited_paper_ids,
                candidate_paper_ids=planned_candidate_ids,
                core_paper_ids=set(state.core_paper_ids or []),
            )
            route = route_after_coverage_audit(
                coverage_result=coverage_result,
                invalid_citation_count=final_validation["invalid_count"],
                revision_attempts_remaining=2,
            )
            logger.info(
                "Final coverage audit completed",
                route=route,
                weighted_coverage=f"{coverage_result.weighted_coverage_bp / 100:.1f}%",
                cluster_coverage=f"{coverage_result.cluster_coverage_bp / 100:.1f}%",
                candidate_coverage=f"{coverage_result.candidate_coverage_bp / 100:.1f}%",
                cited_core=coverage_result.cited_core_count,
                cited_auxiliary=coverage_result.cited_auxiliary_count,
                orphan_clusters=coverage_result.orphan_clusters,
            )
            if route == "fail":
                logger.warning(
                    "Final coverage audit did not pass; preserving generated review with quality warning",
                    weighted_coverage_bp=coverage_result.weighted_coverage_bp,
                    invalid_citation_count=final_validation["invalid_count"],
                    orphan_clusters=coverage_result.orphan_clusters,
                )
        except Exception as e:
            logger.warning("Final coverage audit errored; preserving generated review", error=str(e))
            coverage_result = None
            route = "audit_error"

        # 生成 BibTeX
        bibtex = _generate_bibtex(papers)

        final_review_id = f"review_{state.project_id}"

        logger.info(
            "Review writing completed",
            sections=len(written_sections),
            total_chars=len(final_review),
            references=len(ref_mappings),
        )

        result = {
            "written_section_ids": written_section_ids,
            "final_review_id": final_review_id,
            "final_review": final_review,
            "bibtex": bibtex,
            "coverage_score": coverage_result.candidate_coverage_bp / 10000 if coverage_result is not None else 0.0,
            "weighted_coverage_bp": coverage_result.weighted_coverage_bp if coverage_result is not None else 0,
            "coverage_route": route if 'route' in locals() else "unknown",
            "invalid_citation_count": final_validation["invalid_count"] if 'final_validation' in locals() else 0,
            "weak_citation_support_count": 0,
            "status": "written",
        }

        if tracker:
            await tracker.end_node("write_review", "succeeded", output_summary={
                "section_count": len(written_sections),
                "total_chars": len(final_review),
                "references": len(ref_mappings),
            })
        return result

    except Exception as e:
        import traceback as tb_mod
        if tracker:
            await tracker.end_node("write_review", "failed",
                                   error_message=str(e),
                                   error_traceback=tb_mod.format_exc())
        logger.error("Review writing failed", error=str(e), traceback=tb_mod.format_exc())
        raise


def _render_citation_plan_summary(plan, paper_map: dict) -> str:
    """
    渲染 citation plan 摘要（对齐 Rust 版 render_section_citation_plan_summary）。

    输出候选文献的来源分布和详细列表，帮助 LLM 理解引用候选的构成。
    """
    details = plan.candidate_details if hasattr(plan, "candidate_details") else []
    if not details:
        return ""

    # 来源统计
    source_counts: dict[str, int] = {}
    for d in details:
        src = d.get("source", "unknown")
        if hasattr(src, "value"):
            src = src.value
        source_counts[src] = source_counts.get(src, 0) + 1
    source_str = ", ".join(f"{k}:{v}" for k, v in source_counts.items())

    # 候选列表（最多 30 篇，对齐 Rust 版输出格式）
    candidate_lines = []
    for i, d in enumerate(details[:30]):
        pid = d.get("paper_id", "")
        cluster = d.get("cluster_id", "unknown")
        src = d.get("source", "unknown")
        if hasattr(src, "value"):
            src = src.value
        # 混合图邻居信息（对齐 Rust 版 hybrid_anchor / hybrid_weight）
        anchor = d.get("hybrid_anchor_paper_id")
        weight_bp = d.get("hybrid_weight_basis_points")
        anchor_str = f"; hybrid_anchor={anchor}" if anchor else ""
        weight_str = f"; hybrid_weight={weight_bp}bp" if weight_bp else ""
        candidate_lines.append(
            f"[{i + 1}] paper_id={pid}; cluster={cluster}; source={src}{anchor_str}{weight_str}"
        )

    return (
        f"citation_candidate_policy: section community papers first, then hybrid graph neighbors, "
        f"then broader core/auxiliary fill\n"
        f"citation_candidate_source_counts: {source_str}\n"
        f"citation_candidates:\n" + "\n".join(candidate_lines)
    )


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
