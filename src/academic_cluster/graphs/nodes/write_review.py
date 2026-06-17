"""
综述写作节点 - 生成综述内容

对齐 Rust 版 review_writer 的完整流程：
1. 大纲 → 引用规划（per-section citation allocation）
2. 逐章写作（带证据卡片和分配的引用）
3. 引用校验 → 修订 → 重编号
4. 确定性组装
"""

import asyncio
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


def _build_cluster_context(plan, section: dict, evidence_plan: dict, clusters: list[dict], kg_entities: list[dict]) -> str:
    # key_clusters 用数字索引代替 UUID
    cluster_id_to_idx = {str(c.get("id")): i + 1 for i, c in enumerate(clusters)}
    key_cluster_labels = [str(cluster_id_to_idx.get(str(k), k)) for k in (plan.key_clusters or [])]
    parts = [f"section: {section.get('title', '')}\nsection_name: {section.get('name', 'unnamed')}\nkey_clusters: {', '.join(key_cluster_labels) if key_cluster_labels else 'all available clusters'}"]
    csum = _render_citation_plan_summary(plan, {})
    if csum:
        parts.append(csum)
    sm = evidence_plan.get("support_matrix") or []
    if sm:
        lines = ["section_evidence_support_matrix:"]
        for item in sm[:10]:
            lines.append(f"- paper_id={item.get('paper_id')}; score={item.get('relevance_score')}; source={item.get('candidate_source')}; claim={item.get('claim', '')[:180]}")
        parts.append("\n".join(lines))
    entity_map: dict[str, list[str]] = {}
    for ent in kg_entities:
        for pid in ent.get("paper_ids") or []:
            entity_map.setdefault(pid, []).append(ent.get("name", ""))
    stat_lines = []
    for i, c in enumerate(clusters):
        c_papers = c.get("paper_ids") or []
        ents = list(dict.fromkeys(e for pid in c_papers[:50] for e in entity_map.get(pid, [])))[:12]
        line = f"cluster{i + 1}: {len(c_papers)} papers"
        if ents:
            line += f"; entities: {', '.join(ents)}"
        stat_lines.append(line)
    if stat_lines:
        parts.append("\n".join(stat_lines))
    return "\n".join(parts) or "暂无聚类数据"

def _build_sample_context(plan, paper_map: dict, ec_by_paper: dict) -> str:
    import json as _json
    samples = []
    for idx, pid in enumerate(plan.candidate_paper_ids[:16], 1):
        p = paper_map.get(pid)
        if not p:
            continue
        card_list = ec_by_paper.get(pid, [])
        card = card_list[0] if card_list else None
        if card:
            metric = card.get("metric")
            metric_str = _json.dumps(metric) if isinstance(metric, dict) else (metric or "none")
            samples.append(
                f"[{idx}] paper_id: {pid}\ntitle: {p.get('title', '')}\n"
                f"evidence_card_id: evidence_card:{pid}\n"
                f"claim: {card.get('claim', '')}\n"
                f"evidence_span: {card.get('evidence_span', '')[:200]}\n"
                f"method: {card.get('method', 'unknown') or 'unknown'}\n"
                f"metric: {metric_str}\n"
                f"limitation: {card.get('limitation', 'none') or 'none'}\n"
                f"confidence: {float(card.get('confidence', 0.0)):.2f}"
            )
        else:
            samples.append(
                f"[{idx}] paper_id: {pid}\ntitle: {p.get('title', '')}\n"
                f"evidence_card_id: unavailable\nabstract: {(p.get('abstract') or '')[:300]}"
            )
    return "\n".join(samples) or "暂无论文样本"

async def _revise_section(content: str, evaluation: dict) -> str:
    from ...agents.section_evaluator import revise_section as _do_revise
    return await _do_revise(content, evaluation)


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

        # === Step 2: 两阶段并行写作 ===
        # 先识别需要写的章节（跳过已有的）
        total_sections = len(citation_plans)
        pending_plans: list[tuple[int, Any, Any]] = []
        for plan_idx, plan in enumerate(citation_plans):
            si = plan.section_index
            section = sections[si]
            section_id_key = str(section.get("name", section.get("number", 0)))
            if section_id_key not in existing_sections:
                pending_plans.append((plan_idx, plan, section))

        # 预构建所有章节的上下文数据（非 LLM，纯数据组装）
        section_contexts: list[dict] = []
        for plan_idx, plan, section in pending_plans:
            si = plan.section_index
            next_section_data = sections[si + 1] if si + 1 < len(sections) else None
            section_evidence_plan = section_evidence_plans.get(si, {})
            section_evidence = cards_from_support_matrix(
                section_evidence_plan.get("support_matrix") or []
            )
            if not section_evidence:
                for pid in plan.candidate_paper_ids[:10]:
                    section_evidence.extend(ec_by_paper.get(pid, []))

            section_contexts.append({
                "plan_idx": plan_idx, "plan": plan, "section": section,
                "next_section": next_section_data, "si": si,
                "section_evidence": section_evidence,
                "section_evidence_plan": section_evidence_plan,
                "section_refs": render_section_references(plan, paper_map),
                "section_citation": _section_citation_payload(plan, paper_map),
                "cluster_data": _build_cluster_context(plan, section, section_evidence_plan, clusters, kg_entities),
                "sample_papers": _build_sample_context(plan, paper_map, ec_by_paper),
                "community_context": section_evidence_plan.get("community_context") or render_section_community_context(
                    section_plan=section, clusters=clusters, papers=papers,
                    evidence_cards=evidence_cards, kg_entities=kg_entities,
                ) or None,
                "evidence_limitations": section_evidence_plan.get("evidence_limitations") or render_section_evidence_limitations(
                    section_plan=section, evidence_cards=evidence_cards,
                ) or None,
            })

        # Phase 1: 并行生成所有章节大纲
        outline_concurrency = max(1, min(4, len(section_contexts)))
        outline_semaphore = asyncio.Semaphore(outline_concurrency)
        section_outlines: list[dict | None] = [None] * len(section_contexts)

        async def _gen_outline(ctx: dict, idx: int) -> dict:
            prev_outline = section_outlines[idx - 1] if idx > 0 else None
            async with outline_semaphore:
                return await plan_section_outline(
                    section_plan=ctx["section"],
                    citation_plan=ctx["section_citation"],
                    prev_outline=prev_outline,
                    next_section=ctx["next_section"],
                    clusters=clusters,
                    evidence_cards=ctx["section_evidence"],
                    kg_entities=kg_entities,
                    kg_relations=kg_relations,
                )

        outline_results = await asyncio.gather(
            *[_gen_outline(ctx, i) for i, ctx in enumerate(section_contexts)],
            return_exceptions=True,
        )
        for i, (ctx, result) in enumerate(zip(section_contexts, outline_results)):
            if isinstance(result, Exception):
                logger.error("Section outline failed", title=ctx["section"].get("title"), error=str(result)[:200])
                raise result
            section_outlines[i] = result
            logger.info("Section outline planned", title=ctx["section"].get("title"),
                        paragraphs=len(result.get("paragraphs", [])),
                        core_question=result.get("core_question", "")[:80])

        # 基于全部大纲构建 prev_summary
        prev_lines = []
        for so in section_outlines:
            if so:
                prev_lines.append(f"- {so.get('core_question', '')}: {so.get('narrative_arc', '')}")
        full_prev_summary = "前序章节已覆盖的内容（不要重复）:\n" + "\n".join(prev_lines) if prev_lines else ""

        # Phase 2: 并行撰写 + 评估 + 保存
        write_concurrency = max(1, min(4, len(section_contexts)))
        write_semaphore = asyncio.Semaphore(write_concurrency)

        async def _write_and_save(ctx: dict, idx: int) -> dict:
            outline = section_outlines[idx]
            async with write_semaphore:
                content = await write_section_units(
                    topic=state.query,
                    review_title=review_title,
                    section_plan=ctx["section"],
                    cluster_data=ctx["cluster_data"],
                    sample_papers=ctx["sample_papers"],
                    references=ctx["section_refs"],
                    evidence_cards=ctx["section_evidence"],
                    community_context=ctx["community_context"],
                    evidence_limitations=ctx["evidence_limitations"],
                    section_outline=outline,
                    prev_summary=full_prev_summary,
                    next_outline=ctx["next_section"],
                )

            if isinstance(content, list):
                content = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block) for block in content
                )
            if not content or len(content.strip()) < 50:
                raise ValueError(f"Section '{ctx['section'].get('title')}' produced insufficient content")

            content = strip_section_reference_block(content)
            content = clean_filler_phrases(content)
            content = strip_meta_commentary(content)
            content = strip_prompt_leakage(content)
            content = strip_revision_commentary(content)
            content = strip_body_structure_leakage(content)
            content = strip_author_year_citations(content)
            content = strip_unsupported_precise_metrics(content, ctx["section_evidence"])
            content = normalize_citation_surface(content)

            pid_to_num = {d["paper_id"]: i + 1 for i, d in enumerate(ctx["plan"].candidate_details) if d.get("paper_id")}
            content = replace_uuid_citations(content, pid_to_num)

            target_chars = ctx["section"].get("target_words", 2000) * 2
            if len(content) > target_chars * 2:
                max_chars = int(target_chars * 1.8)
                truncated = content[:max_chars]
                last_para = truncated.rfind("\n\n")
                if last_para > max_chars * 0.6:
                    content = truncated[:last_para]

            # 评估 + 修订循环
            max_refinement = 1
            next_outline_data = None
            if ctx["next_section"]:
                next_outline_data = {
                    "title": ctx["next_section"].get("title", ""),
                    "description": ctx["next_section"].get("description", ""),
                }

            for ref_attempt in range(max_refinement + 1):
                evaluation = await evaluate_section(
                    section_title=ctx["section"].get("title", f"章节 {ctx['plan_idx'] + 1}"),
                    section_draft=content,
                    section_outline=outline,
                    target_words=ctx["section"].get("target_words", 2000),
                    prev_summary=full_prev_summary,
                    next_outline=next_outline_data,
                    references=ctx["section_refs"],
                )
                if ref_attempt < max_refinement and evaluation.get("score", 0) < 70:
                    content = await _revise_section(content, evaluation)
                else:
                    break

            # 保存到 DB
            section_data = {
                "outline_id": state.outline_id,
                "section_id": str(ctx["section"].get("name", ctx["section"].get("number", 0))),
                "content": content,
                "word_count": len(content),
            }
            section_id = await db.save_written_section(section_data)

            return {
                "content": content, "section_id": section_id,
                "evaluation": evaluation, "ctx": ctx,
                "outline": outline,
            }

        write_results = await asyncio.gather(
            *[_write_and_save(ctx, i) for i, ctx in enumerate(section_contexts)],
            return_exceptions=True,
        )

        # 按原始顺序组装结果
        written_sections: list[str] = []
        written_section_ids: list[str] = []
        section_evaluations: list[dict] = []

        write_idx = 0
        for plan_idx, plan in enumerate(citation_plans):
            section = sections[plan.section_index]
            sk = str(section.get("name", section.get("number", 0)))
            if sk in existing_sections:
                ex = existing_sections[sk]
                written_sections.append(ex["content"])
                written_section_ids.append(ex["id"])
            else:
                result = write_results[write_idx]
                write_idx += 1
                if isinstance(result, Exception):
                    logger.error("Section write failed", title=section.get("title"), error=str(result)[:200])
                    raise result
                written_sections.append(result["content"])
                written_section_ids.append(result["section_id"])
                section_evaluations.append(result["evaluation"])

        logger.info("All sections written", total=total_sections,
                     written=len(written_sections), skipped=len(existing_sections))

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
                    logger.warning(
                        "Stripping invalid local citations from section",
                        section=idx,
                        invalid=sorted(invalid_local),
                    )
                    from ...services.citation_utils import strip_invalid_citations
                    remapped_body = strip_invalid_citations(remapped_body, invalid_local)
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
