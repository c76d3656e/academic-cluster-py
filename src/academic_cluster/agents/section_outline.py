"""
Section Outline Planner Agent

为单个 section 生成详细的段落级写作规划。
串行执行：section N 的规划依赖 section N-1 的规划结果。
"""

import json
import re
from typing import Any

import structlog
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..prompts import get_section_outline_prompt
from ..services.llm_client import ainvoke_with_callbacks, create_llm
from ..tools.json_repair import try_parse_json

logger = structlog.get_logger()
DEFAULT_SECTION_OUTLINE_TIMEOUT_S = 180.0


def _normalize_paragraph_word_budget(
    outline: dict[str, Any], target_words: int
) -> dict[str, Any]:
    """Normalize paragraph target_words so their sum follows the section budget."""
    paragraphs = outline.get("paragraphs") if isinstance(outline, dict) else None
    if not isinstance(paragraphs, list) or not paragraphs:
        return outline

    try:
        target_words = int(target_words)
    except (TypeError, ValueError):
        target_words = 0
    if target_words <= 0:
        return outline

    count = len(paragraphs)
    min_para_words = min(180, max(80, target_words // max(count, 1)))
    min_total = min_para_words * count
    if target_words < min_total:
        min_para_words = max(60, target_words // max(count, 1))
        min_total = min_para_words * count

    weights: list[int] = []
    for paragraph in paragraphs:
        try:
            value = (
                int(paragraph.get("target_words") or 0)
                if isinstance(paragraph, dict)
                else 0
            )
        except (TypeError, ValueError):
            value = 0
        weights.append(value if value > 0 else 1)

    weight_sum = sum(weights) or count
    remaining = max(0, target_words - min_total)
    allocated: list[int] = []
    fractions: list[tuple[float, int]] = []
    for idx, weight in enumerate(weights):
        exact_extra = remaining * weight / weight_sum
        extra = int(exact_extra)
        allocated.append(min_para_words + extra)
        fractions.append((exact_extra - extra, idx))

    delta = target_words - sum(allocated)
    for _, idx in sorted(fractions, reverse=True)[: max(0, delta)]:
        allocated[idx] += 1

    for paragraph, words in zip(paragraphs, allocated, strict=False):
        if isinstance(paragraph, dict):
            paragraph["target_words"] = int(words)
    outline["paragraphs"] = paragraphs
    return outline


# =============================================================================
# LLM 调用
# =============================================================================


async def _ainvoke_with_retry(
    agent: ChatOpenAI,
    messages: list[BaseMessage],
    max_retries: int = 2,
    timeout_s: float = DEFAULT_SECTION_OUTLINE_TIMEOUT_S,
) -> Any:
    """带重试的 LLM 调用"""

    @retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=2, min=3, max=30),
        reraise=True,
    )
    async def _call() -> Any:
        return await ainvoke_with_callbacks(agent, messages, timeout=timeout_s)

    return await _call()


# =============================================================================
# 上下文构建
# =============================================================================


def _build_cluster_context(
    clusters: list[dict[str, Any]],
    papers_by_cluster: dict[Any, list[dict[str, Any]]],
    evidence_cards: list[dict[str, Any]],
) -> str:
    """
    构建该 section 关联的聚类上下文文本。

    为每个聚类生成：论文数、top entities、代表性论文标题、相关 evidence cards。
    """
    if not clusters:
        return "暂无聚类数据"

    # 构建 evidence_cards 的 paper_id 索引
    evidence_by_paper: dict[str, list[dict[str, Any]]] = {}
    for card in evidence_cards:
        pid = card.get("paper_id", "")
        if pid:
            evidence_by_paper.setdefault(pid, []).append(card)

    parts = []
    for i, cluster in enumerate(clusters):
        cluster_label = f"聚类{i + 1}"
        cluster_id = cluster.get("id", i)
        paper_ids = cluster.get("paper_ids", [])
        size = len(paper_ids)

        # 获取该聚类关联的论文
        cluster_papers = papers_by_cluster.get(cluster_id, [])

        # 提取 top entities
        entity_counts: dict[str, int] = {}
        for p in cluster_papers:
            for e in p.get("entities", []):
                name = e.get("name", "") if isinstance(e, dict) else str(e)
                if name:
                    entity_counts[name] = entity_counts.get(name, 0) + 1
        top_entities = sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)[
            :8
        ]
        entity_str = ", ".join(f"{name}({cnt})" for name, cnt in top_entities)

        # 代表性论文标题
        sample_titles = []
        for p in cluster_papers[:5]:
            title = p.get("title", "")
            if title:
                sample_titles.append(title)

        # 相关 evidence cards
        cluster_evidence = []
        for pid in paper_ids[:10]:
            for card in evidence_by_paper.get(pid, []):
                claim = card.get("claim", card.get("key_finding", ""))
                if claim:
                    card_id = card.get("id", "")
                    confidence = card.get("confidence", "")
                    cluster_evidence.append(
                        f"[{card_id}] {claim} (confidence={confidence})"
                    )

        line = f"{cluster_label}: {size} 篇论文"
        if sample_titles:
            line += f"; 代表性论文: {'; '.join(sample_titles[:3])}"
        if entity_str:
            line += f"; 关键实体: {entity_str}"
        if cluster_evidence:
            line += f"\n  证据: {'; '.join(cluster_evidence[:5])}"
        parts.append(line)

    return "\n\n".join(parts)


def _build_evidence_context(evidence_cards: list[dict[str, Any]]) -> str:
    """构建 evidence cards 上下文文本"""
    if not evidence_cards:
        return "暂无证据卡片"

    lines = []
    for i, card in enumerate(evidence_cards[:30], 1):
        card_id = card.get("id", f"card_{i}")
        title = card.get("title", card.get("paper_title", ""))
        claim = card.get("claim", card.get("key_finding", ""))
        evidence_span = card.get("evidence_span", "")
        method = card.get("method", "")
        metric = card.get("metric", "")
        confidence = card.get("confidence", "")

        parts = [f"[{card_id}]"]
        if title:
            parts.append(f"论文: {title}")
        if claim:
            parts.append(f"论断: {claim}")
        if evidence_span:
            span_preview = (
                evidence_span[:120] + "..."
                if len(evidence_span) > 120
                else evidence_span
            )
            parts.append(f"证据: {span_preview}")
        if method:
            parts.append(f"方法: {method}")
        if metric:
            parts.append(f"指标: {metric}")
        if confidence:
            parts.append(f"置信度: {confidence}")

        lines.append(" | ".join(parts))

    return "\n".join(lines)


def _build_kg_context(
    kg_entities: list[dict[str, Any]], kg_relations: list[dict[str, Any]]
) -> str:
    """构建知识图谱上下文文本"""
    parts = []

    if kg_entities:
        entity_lines = []
        for e in kg_entities[:30]:
            name = e.get("name", "")
            etype = e.get("entity_type", "")
            if name:
                entity_lines.append(f"{name} ({etype})" if etype else name)
        if entity_lines:
            parts.append("关键实体:\n" + "\n".join(f"- {el}" for el in entity_lines))

    if kg_relations:
        relation_lines = []
        for r in kg_relations[:20]:
            source = r.get("source", "")
            target = r.get("target", "")
            rtype = r.get("relation_type", "")
            if source and target:
                relation_lines.append(
                    f"{source} --[{rtype}]--> {target}"
                    if rtype
                    else f"{source} --> {target}"
                )
        if relation_lines:
            parts.append("关键关系:\n" + "\n".join(f"- {rl}" for rl in relation_lines))

    return "\n\n".join(parts) if parts else "暂无知识图谱数据"


def _build_prev_context(prev_outline: dict[str, Any] | None) -> str:
    """
    构建前序 section 的上下文。

    返回：前序 section 的 core_question、narrative_arc、already_covered、transition_to_next。
    """
    if not prev_outline:
        return ""

    core_question = prev_outline.get("core_question", "")
    narrative_arc = prev_outline.get("narrative_arc", "")
    already_covered = prev_outline.get("already_covered", [])
    transition_to_next = prev_outline.get("transition_to_next", "")

    lines = ["## 前序章节的规划信息（用于衔接和避免重复）"]
    if core_question:
        lines.append(f"核心问题: {core_question}")
    if narrative_arc:
        lines.append(f"论述逻辑: {narrative_arc}")
    if already_covered:
        lines.append("已覆盖论点（本 section 不应重复）:")
        for item in already_covered:
            lines.append(f"  - {item}")
    if transition_to_next:
        lines.append(f"前序 section 的铺垫方向: {transition_to_next}")

    return "\n".join(lines)


def _build_next_hint(next_section: dict[str, Any] | None) -> str:
    """
    构建后序 section 的提示。

    返回：后序 section 的 title、description。
    """
    if not next_section:
        return ""

    title = next_section.get("title", "")
    description = next_section.get("description", "")

    lines = ["## 后续章节信息（用于铺垫）"]
    if title:
        lines.append(f"下一章节标题: {title}")
    if description:
        lines.append(f"下一章节描述: {description}")

    return "\n".join(lines)


# =============================================================================
# JSON 解析与修复
# =============================================================================


def _try_repair_section_outline_json(content: str, target_words: int) -> dict[str, Any]:
    """
    尝试修复被 LLM 截断的 section outline JSON。

    常见截断模式：
    1. 字符串未关闭
    2. 数组/对象未关闭
    3. paragraphs 数组中间截断
    """
    # 提取 core_question
    cq_match = re.search(r'"core_question"\s*:\s*"([^"]*)"', content)
    core_question = cq_match.group(1) if cq_match else ""

    # 提取 narrative_arc
    na_match = re.search(r'"narrative_arc"\s*:\s*"([^"]*)"', content)
    narrative_arc = na_match.group(1) if na_match else ""

    # 提取完整的 paragraph 对象
    paragraphs = []
    para_pattern = re.compile(
        r'\{\s*"index"\s*:\s*(\d+)\s*,'
        r'(?:\s*"task_type"\s*:\s*"([^"]*)"\s*,)?'
        r'\s*"direction"\s*:\s*"([^"]*)"'
        r'(?:\s*,\s*"target_words"\s*:\s*(\d+))?'
        r'(?:\s*,\s*"key_papers"\s*:\s*\[([^\]]*)\])?'
        r'(?:\s*,\s*"key_evidence"\s*:\s*\[([^\]]*)\])?'
        r'(?:\s*,\s*"synthesis_instruction"\s*:\s*"([^"]*)")?'
        r"\s*\}",
        re.DOTALL,
    )

    for m in para_pattern.finditer(content):
        para = {
            "index": int(m.group(1)),
            "task_type": m.group(2) if m.group(2) else "approach",
            "direction": m.group(3),
            "target_words": int(m.group(4)) if m.group(4) else target_words // 4,
        }
        if m.group(5):
            try:
                para["key_papers"] = [
                    x.strip().strip('"') for x in m.group(5).split(",") if x.strip()
                ]
            except Exception:
                para["key_papers"] = []
        else:
            para["key_papers"] = []
        if m.group(6):
            try:
                para["key_evidence"] = [
                    x.strip().strip('"') for x in m.group(6).split(",") if x.strip()
                ]
            except Exception:
                para["key_evidence"] = []
        else:
            para["key_evidence"] = []
        if m.group(7):
            para["synthesis_instruction"] = m.group(7)
        else:
            para["synthesis_instruction"] = "综合相关研究的发现"
        paragraphs.append(para)

    # 提取 transition 和 already_covered
    tfp_match = re.search(r'"transition_from_prev"\s*:\s*"([^"]*)"', content)
    transition_from_prev = tfp_match.group(1) if tfp_match else ""

    ttn_match = re.search(r'"transition_to_next"\s*:\s*"([^"]*)"', content)
    transition_to_next = ttn_match.group(1) if ttn_match else ""

    # 提取 already_covered 数组
    ac_match = re.search(r'"already_covered"\s*:\s*\[([^\]]*)\]', content)
    already_covered = []
    if ac_match:
        try:
            already_covered = [
                x.strip().strip('"') for x in ac_match.group(1).split(",") if x.strip()
            ]
        except Exception:  # nosec B110
            pass

    if paragraphs:
        logger.warning(
            "Repaired truncated section outline JSON",
            original_length=len(content),
            recovered_paragraphs=len(paragraphs),
        )
        return {
            "core_question": core_question,
            "narrative_arc": narrative_arc,
            "paragraphs": paragraphs,
            "transition_from_prev": transition_from_prev,
            "transition_to_next": transition_to_next,
            "already_covered": already_covered,
        }

    logger.error("Failed to repair section outline JSON", content_preview=content[:500])
    raise ValueError(f"LLM returned invalid JSON for section outline: {content[:200]}")


def _parse_response(raw_content: str, target_words: int) -> dict[str, Any]:
    """解析 LLM 响应为 section outline dict，含多层容错"""
    if isinstance(raw_content, list):
        raw_content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in raw_content
        )

    # 策略 1: 直接 JSON 解析
    try:
        return json.loads(raw_content)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        pass

    # 策略 2: 去除 markdown 代码块后解析
    content = raw_content.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(content)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        pass

    # 策略 3: 提取 JSON 对象
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(content[start : end + 1])  # type: ignore[no-any-return]
        except json.JSONDecodeError:
            pass

    # 策略 4: 使用 try_parse_json 工具
    parsed = try_parse_json(raw_content)
    if parsed is not None:
        return parsed  # type: ignore[no-any-return]

    # 策略 5: 正则修复截断 JSON
    if start != -1:
        return _try_repair_section_outline_json(content[start:], target_words)

    raise ValueError(
        f"LLM returned invalid JSON for section outline: {raw_content[:200]}"
    )


# =============================================================================
# Fallback 规划
# =============================================================================


def _fallback_outline(section_plan: dict[str, Any]) -> dict[str, Any]:
    """
    JSON 解析失败时的 fallback 规划。

    按 target_words 均分为 4 段，每段 generic direction。
    """
    target_words = section_plan.get("target_words", 2000)
    per_para = max(120, int(target_words) // 4)

    return {
        "core_question": f"本章节系统梳理{section_plan.get('title', '该领域')}的研究现状与发展趋势",
        "narrative_arc": "研究背景与问题定义 -> 主要方法与技术路线 -> 关键发现与进展 -> 现有不足与未来方向",
        "paragraphs": [
            {
                "index": 1,
                "task_type": "context",
                "direction": "阐述该研究方向的核心问题与科学意义",
                "target_words": per_para,
                "key_papers": [],
                "key_evidence": [],
                "synthesis_instruction": "综合相关研究的问题定义，归纳核心挑战",
            },
            {
                "index": 2,
                "task_type": "approach",
                "direction": "梳理主要研究方法的技术路线与核心思想",
                "target_words": per_para,
                "key_papers": [],
                "key_evidence": [],
                "synthesis_instruction": "对比不同方法的核心思想与适用场景",
            },
            {
                "index": 3,
                "task_type": "result",
                "direction": "分析关键研究发现与实验验证结果",
                "target_words": per_para,
                "key_papers": [],
                "key_evidence": [],
                "synthesis_instruction": "综合多项研究的实验结果，归纳共识与分歧",
            },
            {
                "index": 4,
                "task_type": "limitation",
                "direction": "讨论现有研究的局限性与未来发展方向",
                "target_words": per_para,
                "key_papers": [],
                "key_evidence": [],
                "synthesis_instruction": "评估当前方法的局限性，识别开放问题",
            },
        ],
        "transition_from_prev": "",
        "transition_to_next": "",
        "already_covered": [],
    }


# =============================================================================
# 主函数
# =============================================================================


async def plan_section_outline(
    section_plan: dict[str, Any],
    citation_plan: dict[str, Any],
    prev_outline: dict[str, Any] | None,
    next_section: dict[str, Any] | None,
    clusters: list[dict[str, Any]],
    evidence_cards: list[dict[str, Any]],
    kg_entities: list[dict[str, Any]],
    kg_relations: list[dict[str, Any]],
    *,
    topic: str = "",
) -> dict[str, Any]:
    """
    为单个 section 生成详细的段落级写作规划。

    Args:
        section_plan: 全局大纲中的该 section 信息
            {name, title, description, target_words, key_clusters, key_entities}
        citation_plan: 该 section 的引用规划
            {papers: [...]}
        prev_outline: 前一个 section 的 outline 规划结果（None if first section）
        next_section: 后一个 section 的全局大纲信息（None if last section）
        clusters: 所有聚类数据
        evidence_cards: 该 section 相关的 evidence cards
        kg_entities: KG 实体
        kg_relations: KG 关系

    Returns:
        段落级规划 dict，包含 core_question, narrative_arc, paragraphs,
        transition_from_prev, transition_to_next, already_covered
    """
    target_words = section_plan.get("target_words", 2000)
    section_title = section_plan.get("title", "")
    section_description = section_plan.get("description", "")

    # 构建 paper_id -> paper 映射
    all_papers = []
    for cluster in clusters:
        for pid in cluster.get("paper_ids", []):
            all_papers.append(pid)

    # 获取 citation_plan 中的论文详情
    citation_papers = citation_plan.get("papers", [])
    paper_map = {}
    for p in citation_papers:
        pid = p.get("id", p.get("paper_id", ""))
        if pid:
            paper_map[pid] = p

    # 为聚类附加论文详情
    papers_by_cluster: dict[Any, list[dict[str, Any]]] = {}
    key_clusters = section_plan.get("target_communities") or section_plan.get(
        "key_clusters", []
    )
    for cluster in clusters:
        cid = cluster.get("id", -1)
        cluster_paper_ids = cluster.get("paper_ids", [])
        cluster_papers = []
        for pid in cluster_paper_ids:
            if pid in paper_map:
                cluster_papers.append(paper_map[pid])
        papers_by_cluster[cid] = cluster_papers

    # 筛选相关聚类
    related_clusters = []
    if key_clusters:
        key_cluster_values = {str(value) for value in key_clusters}
        related_clusters = [
            c for c in clusters if str(c.get("id")) in key_cluster_values
        ]
    else:
        related_clusters = clusters

    # 构建上下文
    cluster_context = _build_cluster_context(
        related_clusters, papers_by_cluster, evidence_cards
    )
    evidence_context = _build_evidence_context(evidence_cards)
    kg_context = _build_kg_context(kg_entities, kg_relations)
    prev_context = _build_prev_context(prev_outline)
    next_hint = _build_next_hint(next_section)

    # 构建 core_question_hint
    core_question_hint = section_plan.get("core_question_hint", "")
    core_question_hint_section = ""
    if core_question_hint:
        core_question_hint_section = (
            f"核心问题提示（来自大纲生成阶段）: {core_question_hint}"
        )

    # 构建 topic_contribution 和 debates 上下文
    topic_contribution = section_plan.get("topic_contribution", "")
    topic_contribution_section = ""
    if topic_contribution:
        topic_contribution_section = f"主题贡献: {topic_contribution}"

    debates = section_plan.get("debates", "")
    debates_section = ""
    if debates:
        debates_section = f"学术争论: {debates}"

    # 构建前序/后序 section 上下文块
    prev_section_context_section = ""
    if prev_context:
        prev_section_context_section = prev_context

    next_section_hint_section = ""
    if next_hint:
        next_section_hint_section = next_hint

    # 加载 prompt 模板
    prompt_template = get_section_outline_prompt()
    if not prompt_template:
        logger.warning("section_outline.md prompt not found, using inline fallback")
        prompt_template = (
            "你是一个学术综述的结构规划师。为以下章节生成段落级写作规划。\n\n"
            "## 研究主题\n**{topic}**\n所有段落必须围绕此主题展开。\n\n"
            "章节标题: {section_title}\n章节描述: {section_description}\n"
            "目标字数: {target_words}\n{topic_contribution_section}\n{debates_section}\n\n"
            "{core_question_hint_section}\n\n{cluster_data}\n\n{evidence_cards}\n\n"
            "{kg_summary}\n\n{prev_section_context_section}\n\n{next_section_hint_section}\n\n"
            "返回 JSON: {{core_question, narrative_arc, paragraphs: [{{index, task_type, direction, target_words, "
            "key_papers, key_evidence, synthesis_instruction}}], transition_from_prev, transition_to_next, already_covered}}\n\n"
            "task_type 可选值: context, gap, approach, result, comparison, mechanism, implication, limitation。"
            "每段只做一个任务，相邻段落 task_type 不能相同。"
        )

    prompt = prompt_template.format(
        topic=topic,
        section_title=section_title,
        section_description=section_description,
        target_words=target_words,
        topic_contribution_section=topic_contribution_section,
        debates_section=debates_section,
        core_question_hint_section=core_question_hint_section,
        cluster_data=cluster_context,
        evidence_cards=evidence_context,
        kg_summary=kg_context,
        prev_section_context_section=prev_section_context_section,
        next_section_hint_section=next_section_hint_section,
    )

    # 创建 LLM（低温度以保证规划稳定性）
    agent = create_llm(temperature=0.3, max_tokens=4096)

    messages = [
        SystemMessage(
            content=(
                "你是一个学术综述的结构规划师。你的任务是为章节生成详细的段落级写作规划。"
                "所有内容必须使用中文。严格返回 JSON 格式，不要输出任何额外文字。\n\n"
                "段落-任务映射规则：每个 paragraph 必须包含 task_type 字段，表示该段落承担的唯一分析任务。"
                "可用的 task_type 类型：context（背景）、gap（空白）、approach（方法）、"
                "result（结果）、comparison（对比）、mechanism（机理）、implication（意义）、limitation（局限）。"
                "每段只做一个任务，相邻段落 task_type 不能相同。"
            )
        ),
        HumanMessage(content=prompt),
    ]

    try:
        response = await _ainvoke_with_retry(agent, messages)
        raw_content = response.content
        outline = _parse_response(raw_content, target_words)

        # 验证基本结构
        if not outline.get("paragraphs"):
            logger.warning("Parsed outline has no paragraphs, using fallback")
            return _fallback_outline(section_plan)

        # 确保 paragraph 字段完整
        valid_task_types = {
            "context",
            "gap",
            "approach",
            "result",
            "comparison",
            "mechanism",
            "implication",
            "limitation",
        }
        fallback_task_sequence = [
            "context",
            "gap",
            "approach",
            "result",
            "comparison",
            "mechanism",
            "implication",
            "limitation",
        ]
        for i, para in enumerate(outline["paragraphs"]):
            para.setdefault("index", i + 1)
            para.setdefault("direction", "")
            para.setdefault("target_words", target_words // len(outline["paragraphs"]))
            para.setdefault("key_papers", [])
            para.setdefault("key_evidence", [])
            para.setdefault("synthesis_instruction", "综合相关研究的发现")
            # 验证 task_type：缺失或无效时按位置分配
            tt = para.get("task_type", "")
            if tt not in valid_task_types:
                para["task_type"] = fallback_task_sequence[
                    i % len(fallback_task_sequence)
                ]

        # 确保顶层字段完整
        outline.setdefault("core_question", "")
        outline.setdefault("narrative_arc", "")
        outline.setdefault("transition_from_prev", "")
        outline.setdefault("transition_to_next", "")
        outline.setdefault("already_covered", [])
        outline = _normalize_paragraph_word_budget(outline, target_words)

        logger.info(
            "Section outline planned",
            section_title=section_title,
            paragraph_count=len(outline["paragraphs"]),
            core_question=outline.get("core_question", "")[:80],
        )

        return outline

    except Exception as e:
        logger.error(
            "Section outline planning failed, using fallback",
            section_title=section_title,
            error=str(e),
        )
        return _fallback_outline(section_plan)
