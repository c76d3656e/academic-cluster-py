"""
大纲生成节点 - 生成综述大纲
"""

import traceback

import structlog

from ...agents.writing import generate_outline
from ...config import get_settings
from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


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
    tracker = state.tracker if hasattr(state, 'tracker') else None
    if tracker:
        await tracker.begin_node("outline_generation", "llm", index=4)

    logger.info("Starting outline generation")

    db = get_database()
    settings = get_settings()
    config = state.config or {}
    total_target_words = config.get("total_target_words", settings.writing_total_target_words)

    try:
        # 确保项目存在
        project = await db.get_project(state.project_id)
        if not project:
            await db.save_project({
                "id": state.project_id,
                "name": f"Review: {state.query}",
                "query": state.query,
                "status": "in_progress",
            })

        # 获取聚类信息
        clusters = await db.get_clusters_by_ids(state.cluster_ids)

        # 获取核心论文详情
        core_papers = await db.get_papers_by_ids(state.core_paper_ids)

        # 获取知识图谱实体和关系
        kg_entities = await db.get_kg_entities_by_ids(state.kg_entity_ids)
        kg_relations = await db.get_kg_relations_by_ids(state.kg_relation_ids)

        # 获取证据卡片
        evidence_cards_raw = await db.get_evidence_cards_by_ids(state.evidence_card_ids)

        # 构建知识图谱摘要（对齐 Rust 版）
        entity_types = list(set(e.get("entity_type", "") for e in kg_entities if e.get("entity_type")))
        relation_types = list(set(r.get("relation_type", "") for r in kg_relations if r.get("relation_type")))

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
                {"source": r.get("source"), "target": r.get("target"), "type": r.get("relation_type")}
                for r in kg_relations[:30]
            ],
        }

        # 为每个聚类附加论文信息和实体（对齐 Rust 版 render_cluster_stats）
        paper_map = {p.get("id"): p for p in core_papers}
        # 构建 paper_id -> entity names 映射
        paper_entities = {}
        for e in kg_entities:
            for pid in e.get("paper_ids", []):
                paper_entities.setdefault(pid, []).append(e.get("name", ""))

        for cluster in clusters:
            cluster_paper_ids = cluster.get("paper_ids", [])
            cluster_papers = [paper_map.get(pid, {}) for pid in cluster_paper_ids if pid in paper_map]
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

        # 生成大纲
        outline_data = await generate_outline(
            topic=state.query,
            clusters=clusters,
            kg_summary=kg_summary,
            evidence_cards=evidence_cards_raw,
            total_target_words=total_target_words,
        )

        # 验证大纲数据，失败时使用 fallback
        if not outline_data or not outline_data.get("sections"):
            logger.warning("LLM returned empty outline, using fallback")
            outline_data = _default_outline(state.query, total_target_words)

        # 确保每章 target_words 不低于最低值
        sections = outline_data.get("sections", [])
        total_assigned = sum(s.get("target_words", 0) for s in sections)
        if total_assigned < total_target_words * 0.5 and sections:
            # 按比例分配目标字数
            per_section = total_target_words // len(sections)
            for s in sections:
                if s.get("target_words", 0) < per_section * 0.5:
                    s["target_words"] = per_section
            logger.info("Adjusted section target_words", total=sum(s["target_words"] for s in sections))

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

        result = {
            "outline_id": outline_id,
            "outline_data": outline_data,
            "status": "outline_generated",
        }

        if tracker:
            await tracker.end_node("outline_generation", "succeeded", output_summary={
                "outline_id": outline_id,
                "section_count": len(outline_data.get("sections", [])),
            })
        return result

    except Exception as e:
        if tracker:
            await tracker.end_node("outline_generation", "failed",
                                   error_message=str(e),
                                   error_traceback=traceback.format_exc())
        logger.error("Outline generation failed", error=str(e))
        raise  # 不再 fallback，直接抛出异常


def _default_outline(topic: str, total_target_words: int = 12000) -> dict:
    """LLM 返回无效时的 fallback 大纲（对齐 Rust 版 default_outline_sections）"""
    per_section = total_target_words // 6
    return {
        "title": f"{topic} 综述",
        "sections": [
            {
                "name": "section_0",
                "title": "引言与研究背景",
                "description": "阐述研究问题的科学意义、核心概念界定、现有综述的不足",
                "target_words": int(per_section * 1.2),
                "key_clusters": [],
                "key_entities": [],
            },
            {
                "name": "section_1",
                "title": "研究方法与技术路线",
                "description": "比较代表性方法的核心思想、适用边界与演进脉络",
                "target_words": per_section,
                "key_clusters": [],
                "key_entities": [],
            },
            {
                "name": "section_2",
                "title": "核心研究进展分析",
                "description": "基于聚类结果分析主要研究方向、关键发现与方法差异",
                "target_words": int(per_section * 1.5),
                "key_clusters": [],
                "key_entities": [],
            },
            {
                "name": "section_3",
                "title": "应用场景与案例研究",
                "description": "梳理典型应用场景、实验验证与性能对比",
                "target_words": per_section,
                "key_clusters": [],
                "key_entities": [],
            },
            {
                "name": "section_4",
                "title": "当前局限与挑战",
                "description": "总结数据、方法、评估和部署方面的主要瓶颈",
                "target_words": int(per_section * 0.8),
                "key_clusters": [],
                "key_entities": [],
            },
            {
                "name": "section_5",
                "title": "未来研究方向",
                "description": "识别可测试的后续研究方向和跨学科融合机会",
                "target_words": int(per_section * 0.8),
                "key_clusters": [],
                "key_entities": [],
            },
        ],
    }
