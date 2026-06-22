"""
大纲生成节点 - 生成综述大纲

对齐 SurveyG 的 Foundation->Development->Frontier 三层分类思想：
在大纲生成前对聚类进行层次分类，使综述结构体现研究演进脉络。
"""

import contextlib
import traceback
from datetime import datetime

import structlog

from ...agents.writing import generate_outline
from ...config import get_settings
from ...services.database import get_database
from ...services.observability import get_current_tracker
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()


def _community_memories_to_summaries(memories: list[dict]) -> list[dict]:
    summaries = []
    for memory in memories:
        summaries.append(
            {
                "cluster_id": memory.get("cluster_id"),
                "cluster_label": memory.get("cluster_id"),
                "paper_count": (memory.get("metadata") or {}).get("paper_count", 0)
                if isinstance(memory.get("metadata"), dict)
                else 0,
                "summary": memory.get("summary", ""),
                "key_findings": [
                    item.get("claim") if isinstance(item, dict) else item
                    for item in (memory.get("key_claims") or [])[:8]
                ],
                "representative_methods": memory.get("method_families") or [],
                "limitations": memory.get("limitations") or [],
                "future_directions": memory.get("future_directions") or [],
                "proof_ids": memory.get("proof_ids") or [],
                "coherence_assessment": (memory.get("metadata") or {}).get(
                    "coherence_assessment", {}
                )
                if isinstance(memory.get("metadata"), dict)
                else {},
                "topic_relevance": (memory.get("metadata") or {}).get(
                    "topic_relevance", {}
                )
                if isinstance(memory.get("metadata"), dict)
                else {},
                "evidence_gaps": (memory.get("metadata") or {}).get("evidence_gaps", [])
                if isinstance(memory.get("metadata"), dict)
                else [],
            }
        )
    return summaries


def _normalize_outline_word_budget(
    outline_data: dict,
    total_target_words: int,
    *,
    min_section_words: int = 300,
) -> dict:
    """Force section target_words to sum to the configured review budget."""
    sections = outline_data.get("sections") or []
    if not isinstance(sections, list) or not sections:
        outline_data["sections"] = []
        return outline_data

    try:
        total_target_words = int(total_target_words)
    except (TypeError, ValueError):
        total_target_words = 0
    if total_target_words <= 0:
        return outline_data

    section_count = len(sections)
    effective_min = min(
        min_section_words, max(120, total_target_words // max(section_count, 1))
    )
    min_total = effective_min * section_count
    if total_target_words < min_total:
        effective_min = max(80, total_target_words // max(section_count, 1))
        min_total = effective_min * section_count

    raw_weights: list[int] = []
    for section in sections:
        if not isinstance(section, dict):
            raw_weights.append(1)
            continue
        try:
            value = int(section.get("target_words") or 0)
        except (TypeError, ValueError):
            value = 0
        raw_weights.append(value if value > 0 else 1)

    weight_sum = sum(raw_weights) or section_count
    remaining = max(0, total_target_words - min_total)
    allocated = []
    fractions = []
    for idx, weight in enumerate(raw_weights):
        exact_extra = remaining * weight / weight_sum
        extra = int(exact_extra)
        allocated.append(effective_min + extra)
        fractions.append((exact_extra - extra, idx))

    delta = total_target_words - sum(allocated)
    for _, idx in sorted(fractions, reverse=True)[: max(0, delta)]:
        allocated[idx] += 1

    for section, target in zip(sections, allocated, strict=False):
        if isinstance(section, dict):
            section["target_words"] = int(target)

    outline_data["sections"] = sections
    outline_data["total_target_words"] = total_target_words
    return outline_data


def _normalize_outline_sections(
    outline_data: dict,
    community_memories: list[dict],
    total_target_words: int | None = None,
) -> dict:
    sections = outline_data.get("sections") or []
    if not isinstance(sections, list):
        sections = []
    memories = community_memories or []
    memory_by_cluster = {
        str(m.get("cluster_id")): m for m in memories if m.get("cluster_id")
    }
    all_cluster_ids = list(memory_by_cluster.keys())

    for idx, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        target = (
            section.get("target_communities")
            or section.get("key_clusters")
            or section.get("clusters")
            or []
        )
        target = [str(x) for x in target if str(x) in memory_by_cluster]
        if not target and all_cluster_ids:
            target = (
                all_cluster_ids[idx :: max(1, len(sections))] or all_cluster_ids[:1]
            )

        related = [memory_by_cluster[cid] for cid in target if cid in memory_by_cluster]
        section["target_communities"] = target
        section["method_families"] = (
            section.get("method_families")
            or [
                method
                for memory in related
                for method in (memory.get("method_families") or [])
            ][:12]
        )
        section["expected_claims"] = (
            section.get("expected_claims")
            or [
                claim
                for memory in related
                for claim in (memory.get("key_claims") or [])
            ][:12]
        )
        section["limitations_to_cover"] = (
            section.get("limitations_to_cover")
            or [
                item for memory in related for item in (memory.get("limitations") or [])
            ][:8]
        )
        section["future_directions_to_cover"] = (
            section.get("future_directions_to_cover")
            or [
                item
                for memory in related
                for item in (memory.get("future_directions") or [])
            ][:8]
        )
        section["proof_ids"] = (
            section.get("proof_ids")
            or [
                proof for memory in related for proof in (memory.get("proof_ids") or [])
            ][:24]
        )
        section["community_synthesis"] = (
            section.get("community_synthesis")
            or [
                {
                    "cluster_id": memory.get("cluster_id"),
                    "summary": memory.get("summary", ""),
                    "coherence_assessment": (memory.get("metadata") or {}).get(
                        "coherence_assessment", {}
                    )
                    if isinstance(memory.get("metadata"), dict)
                    else {},
                    "topic_relevance": (memory.get("metadata") or {}).get(
                        "topic_relevance", {}
                    )
                    if isinstance(memory.get("metadata"), dict)
                    else {},
                    "evidence_gaps": (memory.get("metadata") or {}).get(
                        "evidence_gaps", []
                    )
                    if isinstance(memory.get("metadata"), dict)
                    else [],
                }
                for memory in related
            ][:6]
        )
        section.setdefault(
            "section_role", section.get("role") or section.get("description") or ""
        )
        section.setdefault(
            "previous_section_dependency",
            sections[idx - 1].get("title")
            if idx > 0 and isinstance(sections[idx - 1], dict)
            else "",
        )
        section.setdefault(
            "next_section_dependency",
            sections[idx + 1].get("title")
            if idx + 1 < len(sections) and isinstance(sections[idx + 1], dict)
            else "",
        )

    outline_data["sections"] = sections
    if total_target_words is not None:
        outline_data = _normalize_outline_word_budget(outline_data, total_target_words)
    return outline_data


# ---------------------------------------------------------------------------
# 层次分类：Foundation / Development / Frontier
# ---------------------------------------------------------------------------

# entity_type -> 默认层的映射表
_ENTITY_TYPE_LAYER_MAP: dict[str, str] = {
    # 方法/算法类 -> Development
    "method": "development",
    "algorithm": "development",
    "technique": "development",
    "approach": "development",
    "model": "development",
    "framework": "development",
    # 问题/应用类 -> Foundation
    "problem": "foundation",
    "application": "foundation",
    "task": "foundation",
    "dataset": "foundation",
    "benchmark": "foundation",
    # 新概念/前沿类 -> Frontier
    "concept": "frontier",
    "theory": "frontier",
    "hypothesis": "frontier",
}


def _classify_cluster_layers(
    clusters: list[dict],
    kg_entities: list[dict],
    core_papers: list[dict],
    evidence_cards: list[dict] | None = None,
) -> dict[str, str]:
    """
    对聚类进行 Foundation / Development / Frontier 层次分类。

    分类依据（按优先级）：
    1. 论文发表年份：较早 -> Foundation，较近 -> Frontier
    2. 被引次数：高被引 -> Foundation
    3. 聚类内实体的类型：参见 _ENTITY_TYPE_LAYER_MAP
    4. evidence cards 的 confidence：高 confidence -> Foundation/Development，
       低 confidence -> Frontier
    5. 信息不足时默认 "development"

    Args:
        clusters: 聚类列表，每个含 id 和 paper_ids
        kg_entities: 知识图谱实体列表
        core_papers: 核心论文详情列表
        evidence_cards: 证据卡片列表

    Returns:
        {cluster_id: "foundation"|"development"|"frontier"} 映射
    """
    current_year = datetime.now().year

    # 预计算查找表
    paper_map = {p.get("id"): p for p in core_papers}

    # paper_id -> entity_type 列表
    entity_types_by_paper: dict[str, list[str]] = {}
    for ent in kg_entities:
        etype = (ent.get("entity_type") or "").lower()
        for pid in ent.get("paper_ids") or []:
            entity_types_by_paper.setdefault(pid, []).append(etype)

    # cluster_id -> evidence cards
    cards_by_cluster: dict[str, list[dict]] = {}
    if evidence_cards:
        for card in evidence_cards:
            cid = card.get("cluster_id", "")
            if cid:
                cards_by_cluster.setdefault(cid, []).append(card)

    result: dict[str, str] = {}

    for cluster in clusters:
        cid = cluster.get("id", "")
        paper_ids = cluster.get("paper_ids", [])
        if not paper_ids:
            result[cid] = "development"
            continue

        # --- 信号收集 ---
        years: list[int] = []
        citations: list[int] = []
        entity_types: list[str] = []
        confidences: list[float] = []

        for pid in paper_ids:
            p = paper_map.get(pid, {})
            # 年份
            pub_date = p.get("publication_date", "")
            if pub_date:
                try:
                    year = int(str(pub_date)[:4])
                    years.append(year)
                except (ValueError, TypeError):
                    pass
            # 被引次数
            cc = p.get("citation_count")
            if cc is not None:
                with contextlib.suppress(ValueError, TypeError):
                    citations.append(int(cc))
            # 实体类型
            entity_types.extend(entity_types_by_paper.get(pid, []))

        # evidence confidence
        for card in cards_by_cluster.get(cid, []):
            conf = card.get("confidence")
            if conf is not None:
                with contextlib.suppress(ValueError, TypeError):
                    confidences.append(float(conf))

        # --- 评分 ---
        foundation_score = 0.0
        frontier_score = 0.0

        # (a) 年份信号
        if years:
            avg_year = sum(years) / len(years)
            if avg_year <= current_year - 8:
                foundation_score += 2.0
            elif avg_year <= current_year - 4:
                foundation_score += 0.5
            else:
                frontier_score += 1.5

        # (b) 被引信号
        if citations:
            avg_cite = sum(citations) / len(citations)
            if avg_cite >= 100:
                foundation_score += 2.0
            elif avg_cite >= 30:
                foundation_score += 1.0
            elif avg_cite < 5:
                frontier_score += 0.5

        # (c) 实体类型信号
        type_counts: dict[str, int] = {}
        for t in entity_types:
            mapped = _ENTITY_TYPE_LAYER_MAP.get(t)
            if mapped:
                type_counts[mapped] = type_counts.get(mapped, 0) + 1
        total_mapped = sum(type_counts.values())
        if total_mapped > 0:
            foundation_ratio = type_counts.get("foundation", 0) / total_mapped
            frontier_ratio = type_counts.get("frontier", 0) / total_mapped
            type_counts.get("development", 0) / total_mapped
            foundation_score += foundation_ratio * 2.0
            frontier_score += frontier_ratio * 2.0
            # development 实体多时不额外加分，作为默认

        # (d) confidence 信号
        if confidences:
            avg_conf = sum(confidences) / len(confidences)
            if avg_conf >= 0.7:
                foundation_score += 1.0
            elif avg_conf < 0.4:
                frontier_score += 1.0

        # --- 判定 ---
        if foundation_score > frontier_score and foundation_score >= 1.5:
            result[cid] = "foundation"
        elif frontier_score > foundation_score and frontier_score >= 1.5:
            result[cid] = "frontier"
        else:
            result[cid] = "development"

    return result


async def outline_generation_node(state: PipelineState) -> dict:
    """
    生成综述大纲

    使用 LLM 基于聚类结果和知识图谱生成综述大纲：
    - 分析每个社区的主要主题
    - 确定章节结构
    - 生成章节描述和关键点
    - 确定每个章节对应的社区

    生成大纲后，图会中断等待用户确认。
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("outline_generation", "llm", index=4)

    logger.info("Starting outline generation")

    db = get_database()
    settings = get_settings()
    config = state.config or {}
    total_target_words = config.get(
        "total_target_words", settings.writing_total_target_words
    )

    try:
        # 确保项目存在
        project = await db.get_project(state.project_id)
        if not project:
            await db.save_project(
                {
                    "id": state.project_id,
                    "name": f"Review: {state.query}",
                    "query": state.query,
                    "status": "in_progress",
                }
            )

        # 获取聚类信息
        clusters = await db.get_clusters_by_ids(state.cluster_ids)

        # 获取核心论文详情
        review_paper_ids = list(
            dict.fromkeys(
                list(state.core_paper_ids or []) + list(state.auxiliary_paper_ids or [])
            )
        )
        core_papers = await db.get_papers_by_ids(
            review_paper_ids or state.core_paper_ids
        )

        # 获取知识图谱实体和关系
        kg_entities = await db.get_kg_entities_by_ids(state.kg_entity_ids)
        kg_relations = await db.get_kg_relations_by_ids(state.kg_relation_ids)

        # 获取证据卡片
        evidence_cards_raw = await db.get_evidence_cards_by_ids(state.evidence_card_ids)

        # 构建知识图谱摘要（对齐 Rust 版）
        entity_types = list(
            {e.get("entity_type", "") for e in kg_entities if e.get("entity_type")}
        )
        relation_types = list(
            {r.get("relation_type", "") for r in kg_relations if r.get("relation_type")}
        )

        kg_summary = {
            "entity_types": entity_types,
            "relation_types": relation_types,
            "entity_count": len(kg_entities),
            "relation_count": len(kg_relations),
            "entities": [
                {"name": e.get("name"), "type": e.get("entity_type")}
                for e in kg_entities[:50]
            ],
            "relations": [
                {
                    "source": r.get("source"),
                    "target": r.get("target"),
                    "type": r.get("relation_type"),
                }
                for r in kg_relations[:30]
            ],
        }

        # 为每个聚类附加论文信息和实体（对齐 Rust 版 render_cluster_stats）
        paper_map = {p.get("id"): p for p in core_papers}
        # 构建 paper_id -> entity names 映射
        paper_entities = {}
        for e in kg_entities:
            for pid in e.get("paper_ids") or []:
                paper_entities.setdefault(pid, []).append(e.get("name", ""))

        for cluster in clusters:
            cluster_paper_ids = cluster.get("paper_ids", [])
            cluster_papers = [
                paper_map.get(pid, {}) for pid in cluster_paper_ids if pid in paper_map
            ]
            # 附加实体信息
            for p in cluster_papers:
                pid = p.get("id", "")
                p["entities"] = [{"name": n} for n in paper_entities.get(pid, [])[:12]]
            cluster["papers"] = [
                {
                    "title": p.get("title", ""),
                    "abstract": (p.get("abstract", "") or "")[:200],
                    "entities": p.get("entities", []),
                }
                for p in cluster_papers
            ]

        await send_progress(
            state.project_id,
            "outline_generation",
            "大纲生成中，正在规划章节结构...",
        )

        # 构建社区摘要（从 evidence cards 聚合每个聚类的关键发现和代表性方法）
        community_memories = await db.get_community_memories_by_ids(
            state.community_memory_ids
        )
        if not community_memories:
            community_memories = await db.get_community_memories_by_project(
                state.project_id
            )
        community_summaries = _community_memories_to_summaries(community_memories)
        if not community_summaries:
            community_summaries = _build_community_summaries(
                clusters, evidence_cards_raw
            )

        # 层次分类：Foundation / Development / Frontier
        cluster_layers = _classify_cluster_layers(
            clusters=clusters,
            kg_entities=kg_entities,
            core_papers=core_papers,
            evidence_cards=evidence_cards_raw,
        )
        logger.info(
            "Cluster layer classification completed",
            layers={
                v: sum(1 for x in cluster_layers.values() if x == v)
                for v in ("foundation", "development", "frontier")
            },
        )

        # 生成大纲
        outline_data = await generate_outline(
            topic=state.query,
            clusters=clusters,
            kg_summary=kg_summary,
            evidence_cards=evidence_cards_raw,
            community_summaries=community_summaries,
            cluster_layers=cluster_layers,
        )

        # 验证大纲数据，失败时使用 fallback
        sections = outline_data.get("sections", []) if outline_data else []
        if not outline_data or len(sections) < 3:
            logger.warning(
                "LLM returned invalid outline (sections < 3), using fallback",
                section_count=len(sections),
            )
            outline_data = _default_outline(state.query)

        outline_data = _normalize_outline_sections(
            outline_data,
            community_memories,
            total_target_words=total_target_words,
        )

        # 设置项目 ID
        outline_data["project_id"] = state.project_id

        # 保存大纲
        outline_id = await db.save_outline(outline_data)

        logger.info(
            "Outline generation completed",
            outline_id=outline_id,
            title=outline_data.get("title"),
            sections=len(outline_data.get("sections", [])),
        )

        section_count = len(outline_data.get("sections", []))
        await send_progress(
            state.project_id,
            "outline_generation",
            f"大纲生成完成，规划 {section_count} 个章节",
            detail={"section_count": section_count, "outline_id": outline_id},
        )

        result = {
            "outline_id": outline_id,
            "outline_data": outline_data,
            "status": "outline_generated",
        }

        if tracker:
            await tracker.end_node(
                "outline_generation",
                "succeeded",
                output_summary={
                    "outline_id": outline_id,
                    "section_count": len(outline_data.get("sections", [])),
                },
            )
        return result

    except Exception as e:
        if tracker:
            await tracker.end_node(
                "outline_generation",
                "failed",
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )
        logger.error("Outline generation failed", error=str(e))
        raise  # 不再 fallback，直接抛出异常


def _build_community_summaries(
    clusters: list[dict], evidence_cards: list[dict]
) -> list[dict]:
    """
    从 evidence cards 聚合每个聚类的摘要信息。

    为每个聚类提取：
    - key_findings: evidence cards 的 claim（前 3 个）
    - representative_methods: evidence cards 的 method（去重前 3 个）
    """
    # 按 cluster_id 分组 evidence cards
    cards_by_cluster: dict[str, list[dict]] = {}
    for card in evidence_cards:
        cid = card.get("cluster_id", "")
        if cid:
            cards_by_cluster.setdefault(cid, []).append(card)

    summaries = []
    for cluster in clusters:
        cid = cluster.get("id", "")
        cards = cards_by_cluster.get(cid, [])
        if not cards:
            continue

        # 提取 key_findings（claim，前 3 个）
        key_findings = []
        for card in cards:
            claim = card.get("claim", card.get("key_finding", ""))
            if claim and claim not in key_findings:
                key_findings.append(claim)
            if len(key_findings) >= 3:
                break

        # 提取 representative_methods（method，去重前 3 个）
        methods = []
        for card in cards:
            method = card.get("method", "")
            if method and method not in methods:
                methods.append(method)
            if len(methods) >= 3:
                break

        if key_findings or methods:
            summaries.append(
                {
                    "cluster_id": cid,
                    "cluster_label": cluster.get("label", cluster.get("name", cid)),
                    "paper_count": len(cluster.get("paper_ids", [])),
                    "key_findings": key_findings,
                    "representative_methods": methods,
                }
            )

    return summaries


def _default_outline(topic: str, total_target_words: int = 3700) -> dict:
    """LLM 返回无效时的 fallback 大纲（对齐 Rust 版 default_outline_sections）"""
    return {
        "title": f"{topic} 综述",
        "sections": [
            {
                "name": "section_0",
                "title": "引言与研究背景",
                "description": "阐述研究问题的科学意义、核心概念界定、现有综述的不足",
                "target_words": 800,
                "key_clusters": [],
                "key_entities": [],
            },
            {
                "name": "section_1",
                "title": "研究方法与技术路线",
                "description": "比较代表性方法的核心思想、适用边界与演进脉络",
                "target_words": 700,
                "key_clusters": [],
                "key_entities": [],
            },
            {
                "name": "section_2",
                "title": "核心研究进展分析",
                "description": "基于聚类结果分析主要研究方向、关键发现与方法差异",
                "target_words": 1200,
                "key_clusters": [],
                "key_entities": [],
            },
            {
                "name": "section_3",
                "title": "应用场景与案例研究",
                "description": "梳理典型应用场景、实验验证与性能对比",
                "target_words": 500,
                "key_clusters": [],
                "key_entities": [],
            },
            {
                "name": "section_4",
                "title": "未来研究方向与展望",
                "description": "识别可测试的后续研究方向和跨学科融合机会",
                "target_words": 500,
                "key_clusters": [],
                "key_entities": [],
            },
        ],
    }
