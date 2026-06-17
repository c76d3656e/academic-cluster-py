"""
写作 Agent

负责生成综述内容，包括大纲、章节和引用。
参考 Rust 版本的 prompt 设计，提供高质量的学术写作指导。

对齐 Rust 版 academic-cluster-rs 的关键改进：
- 章节写作注入 community context 摘要
- assemble_review 统一风格和过渡语句
- evidence limitations 上下文
"""

import json
import os
import re

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..prompts import (
    get_generate_outline_prompt,
    get_review_structure_prompt,
    get_review_style_prompt,
    get_write_section_prompt,
)
from ..prompts.writing_rules import (
    format_banned_phrases_for_prompt,
)

logger = structlog.get_logger()

_WRITING_CONTEXT_CHAR_BUDGET = 52000
_REFINE_SECTION_UNITS_ENV = "WRITING_REFINE_SECTION_UNITS"
DEFAULT_WRITING_TIMEOUT_S = 180.0
DEFAULT_OUTLINE_TIMEOUT_S = 180.0
DEFAULT_SECTION_WRITE_TIMEOUT_S = 180.0
DEFAULT_SECTION_REFINE_TIMEOUT_S = 180.0


def _clip_text_block(text: str | None, max_chars: int) -> str:
    """Keep prompt blocks within model context budget while preserving boundaries."""
    if not text:
        return ""
    text = str(text)
    if len(text) <= max_chars:
        return text
    clipped = text[:max_chars]
    boundary = max(clipped.rfind("\n\n"), clipped.rfind("\n- "), clipped.rfind("\n["))
    if boundary > max_chars * 0.65:
        clipped = clipped[:boundary]
    return clipped.rstrip() + "\n...[truncated for context budget]"


def _compact_section_inputs(
    cluster_data: str,
    sample_papers: str,
    references: str,
    community_context: str | None,
    evidence_limitations: str | None,
    evidence_cards: list[dict] | None,
) -> tuple[str, str, str, str | None, str | None, list[dict] | None]:
    return (
        _clip_text_block(cluster_data, 9000),
        _clip_text_block(sample_papers, 12000),
        _clip_text_block(references, 10000),
        _clip_text_block(community_context, 7000) if community_context else None,
        _clip_text_block(evidence_limitations, 5000) if evidence_limitations else None,
        list(evidence_cards or [])[:8] if evidence_cards else evidence_cards,
    )


def _estimate_prompt_tokens(text: str) -> int:
    # Conservative mixed Chinese/English estimate for OpenAI-compatible 32k models.
    return max(1, len(text) // 2)


def _writing_max_tokens_for_prompt(prompt: str, requested: int = 4096) -> int:
    remaining = 32768 - _estimate_prompt_tokens(prompt) - 512
    return max(1024, min(requested, remaining))


def _should_refine_section_units() -> bool:
    """Optional LLM paragraph polishing is expensive; keep it opt-in for E2E stability."""
    value = os.getenv(_REFINE_SECTION_UNITS_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _fallback_section_text(
    section_plan: dict,
    references: str,
    evidence_cards: list[dict] | None = None,
) -> str:
    """Build a grounded fallback paragraph when the writing LLM cannot finish."""
    title = str(section_plan.get("title") or "本节").strip()
    description = str(section_plan.get("description") or "").strip()
    citation_numbers = re.findall(r"\[(\d+)\]", references or "")
    citation = f"[{citation_numbers[0]}]" if citation_numbers else ""

    evidence_bits = []
    for card in list(evidence_cards or [])[:3]:
        claim = str(card.get("claim") or "").strip()
        method = str(card.get("method") or "").strip()
        if claim:
            evidence_bits.append(claim)
        elif method:
            evidence_bits.append(method)

    body = description or f"{title}围绕该研究方向中的代表性问题展开。"
    if evidence_bits:
        body += " 现有证据显示，" + "；".join(evidence_bits[:2]) + "。"
    if citation:
        body += f" 这一判断需要结合候选文献{citation}继续细化。"
    else:
        body += " 由于当前写作调用未返回可用正文，本段保留为降级草稿，后续应结合证据卡片继续扩展。"
    return body


# =============================================================================
# 文献堆叠检测（Synthesis-First 违规检测）
# =============================================================================

# 检测"Author A [N] verb ... Author B [N] verb ..."的逐篇罗列模式
_PAPER_STACKING_PATTERNS = [
    # 中文模式：张三 [1] 提出了...李四 [2] 提出了...
    re.compile(
        r"[一-鿿]{2,4}\s*\[\d+(?:,\s*\d+)*\]\s*"
        r"(?:提出|发现|证明|指出|认为|采用|设计|给出|报告|表明|展示了?)\b"
        r".*?[一-鿿]{2,4}\s*\[\d+(?:,\s*\d+)*\]\s*"
        r"(?:提出|发现|证明|指出|认为|采用|设计|给出|报告|表明|展示了?)\b",
        re.DOTALL,
    ),
    # 英文模式：Author A [N] proposed... Author B [N] proposed...
    re.compile(
        r"[A-Z][a-z]+\s+(?:et\s+al\.?\s+)?\[\d+(?:,\s*\d+)*\]\s*"
        r"(?:proposed|presented|developed|introduced|showed|demonstrated|found|reported|designed)\b"
        r".*?[A-Z][a-z]+\s+(?:et\s+al\.?\s+)?\[\d+(?:,\s*\d+)*\]\s*"
        r"(?:proposed|presented|developed|introduced|showed|demonstrated|found|reported|designed)\b",
        re.DOTALL,
    ),
]


def detect_paper_stacking(text: str) -> list[str]:
    """
    检测综述文本中的文献堆叠模式（逐篇罗列）。

    Args:
        text: 章节文本

    Returns:
        违规段落的警告列表，空列表表示未检测到问题
    """
    warnings = []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    for i, para in enumerate(paragraphs, 1):
        # 检测连续的"[N] + 动词"模式（3 处以上视为堆叠）
        citation_verb_matches = re.findall(
            r"\[\d+(?:,\s*\d+)*\]\s*"
            r"(?:提出|发现|证明|指出|认为|采用|设计|给出|报告|表明|展示|"
            r"proposed|presented|developed|introduced|showed|demonstrated|found|reported|designed)",
            para,
        )
        if len(citation_verb_matches) >= 3:
            warnings.append(
                f"段落 {i}: 检测到文献堆叠模式（{len(citation_verb_matches)} 处连续引用-动词结构），"
                "建议改为按主题/机制进行综合论述"
            )
            continue

        # 检测正则模式
        for pattern in _PAPER_STACKING_PATTERNS:
            if pattern.search(para):
                warnings.append(
                    f"段落 {i}: 检测到逐篇罗列模式，建议改为综合对比或归纳"
                )
                break

    return warnings


async def _ainvoke_with_retry(
    agent,
    messages,
    max_retries=2,
    timeout_s: float = DEFAULT_WRITING_TIMEOUT_S,
):
    """带重试的 LLM 调用"""
    from ..services.llm_client import ainvoke_with_callbacks

    @retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=2, min=3, max=30),
        reraise=True,
    )
    async def _call():
        return await ainvoke_with_callbacks(agent, messages, timeout=timeout_s)

    return await _call()


# =============================================================================
# Agent 创建
# =============================================================================

def create_writing_agent(
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
) -> ChatOpenAI:
    """
    创建写作 Agent

    Args:
        model: LLM 模型名称
        temperature: 温度参数，写作需要适度的创造性

    Returns:
        LLM 实例
    """
    from ..services.llm_client import create_llm

    llm = create_llm(temperature=temperature, max_tokens=max_tokens)
    logger.info("Writing agent created")
    return llm


# =============================================================================
# 写作函数
# =============================================================================

async def generate_outline(
    topic: str,
    clusters: list[dict],
    kg_summary: dict,
    evidence_cards: list[dict] | None = None,
    community_summaries: list[dict] | None = None,
    cluster_layers: dict[str, str] | None = None,
) -> dict:
    """
    生成综述大纲

    Args:
        topic: 研究主题
        clusters: 聚类信息列表
        kg_summary: 知识图谱摘要
        evidence_cards: 证据卡片列表
        community_summaries: 社区摘要列表（每个聚类的 key_findings 和 representative_methods）
        cluster_layers: 聚类层次分类 {cluster_id: "foundation"|"development"|"frontier"}

    Returns:
        大纲数据
    """
    agent = create_writing_agent()

    # 层次标签中文映射
    _LAYER_LABELS = {
        "foundation": "Foundation(基础层)",
        "development": "Development(发展层)",
        "frontier": "Frontier(前沿层)",
    }

    # 构建聚类统计上下文（对齐 Rust 版 render_cluster_stats），附加层次标签
    clusters_context_parts = []
    for i, c in enumerate(clusters):
        cluster_size = c.get("size", 0)
        papers = c.get("papers", [])
        # 提取该聚类中的实体名称
        entity_names = []
        for p in papers:
            for e in p.get("entities", []):
                name = e.get("name", "") if isinstance(e, dict) else str(e)
                if name and name not in entity_names:
                    entity_names.append(name)
        entity_str = ", ".join(entity_names[:12]) if entity_names else ""
        cid = c.get("id", str(i))
        layer = (cluster_layers or {}).get(cid, "development")
        layer_tag = _LAYER_LABELS.get(layer, "Development(发展层)")
        line = f"cluster {i}: {cluster_size} papers; layer: {layer_tag}"
        if entity_str:
            line += f"; entities: {entity_str}"
        clusters_context_parts.append(line)
    clusters_context = "\n".join(clusters_context_parts) if clusters_context_parts else "暂无聚类数据"

    # 构建层次分类指导段落
    layer_guidance_block = ""
    if cluster_layers:
        # 按层分组
        layer_groups: dict[str, list[int]] = {"foundation": [], "development": [], "frontier": []}
        for idx, c in enumerate(clusters):
            cid = c.get("id", str(idx))
            layer = cluster_layers.get(cid, "development")
            layer_groups.setdefault(layer, []).append(idx)

        layer_lines = ["## 聚类层次分类（指导大纲结构）"]
        layer_lines.append("")
        layer_lines.append("以下聚类已按研究演进阶段分类，请据此安排章节顺序：")
        layer_lines.append("")
        if layer_groups.get("foundation"):
            indices = ", ".join(f"cluster {i}" for i in layer_groups["foundation"])
            layer_lines.append(f"- **Foundation（基础层）**: {indices}")
            layer_lines.append("  → 应安排在综述前部（研究背景、经典方法、奠基性工作）")
        if layer_groups.get("development"):
            indices = ", ".join(f"cluster {i}" for i in layer_groups["development"])
            layer_lines.append(f"- **Development（发展层）**: {indices}")
            layer_lines.append("  → 应安排在综述中部（技术演进、方法对比、改进工作）")
        if layer_groups.get("frontier"):
            indices = ", ".join(f"cluster {i}" for i in layer_groups["frontier"])
            layer_lines.append(f"- **Frontier（前沿层）**: {indices}")
            layer_lines.append("  → 应安排在综述后部（前沿方向、未来展望、新兴探索）")
        layer_guidance_block = "\n".join(layer_lines)

    # 构建知识图谱摘要上下文（对齐 Rust 版 render_kg_summary）
    kg_parts = []
    entities = kg_summary.get("entities", [])
    if entities:
        entity_counts = {}
        for e in entities[:50]:
            name = e.get("name", "")
            if name:
                entity_counts[name] = entity_counts.get(name, 0) + 1
        sorted_entities = sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)[:30]
        for name, count in sorted_entities:
            kg_parts.append(f"{name}: {count} papers")
    kg_context = "\n".join(kg_parts) if kg_parts else "暂无知识图谱数据"

    # 附加证据卡片（对齐 Rust 版 render_evidence_cards）
    if evidence_cards:
        card_lines = []
        for idx, card in enumerate(evidence_cards[:20], 1):
            title = card.get("title", card.get("paper_title", ""))
            year = card.get("year", "")
            claim = card.get("claim", card.get("key_finding", ""))
            confidence = card.get("confidence", "")
            line = f"{idx}. {title} ({year})"
            if claim:
                line += f" — {claim}"
            if confidence:
                line += f" [confidence={confidence}]"
            card_lines.append(line)
        if card_lines:
            kg_context += "\n\nEvidence cards:\n" + "\n".join(card_lines)

    # 构建社区摘要上下文
    community_context = ""
    if community_summaries:
        cs_parts = []
        for cs in community_summaries:
            label = cs.get("cluster_label", cs.get("cluster_id", ""))
            paper_count = cs.get("paper_count", 0)
            findings = cs.get("key_findings", [])
            methods = cs.get("representative_methods", [])
            lines = [f"### {label} ({paper_count} papers)"]
            if findings:
                lines.append("key_findings:")
                for f in findings:
                    lines.append(f"  - {f}")
            if methods:
                lines.append("representative_methods: " + "; ".join(methods))
            cs_parts.append("\n".join(lines))
        community_context = "\n\n".join(cs_parts)

    # 加载大纲生成提示模板
    outline_prompt_template = get_generate_outline_prompt()
    if not outline_prompt_template:
        outline_prompt_template = """你是一位精通学术写作的综述专家。请基于以下聚类分析结果和知识图谱数据，生成一份综述文章的详细大纲。

研究主题: {topic}

## 聚类统计（Cluster Stats）
{cluster_stats}

## 知识图谱摘要（关键实体和关系）
{kg_summary}

{community_summaries}

请生成一份有深度的综述大纲，返回以下 JSON 格式：

{{
  "title": "综述标题——应精准概括研究主题与切入点，体现学术深度",
  "sections": [
    {{
      "name": "section_0",
      "title": "具体、学术化的章节标题",
      "description": "本章的写作目标与核心论点概述",
      "target_words": 2000,
      "key_clusters": [0],
      "key_entities": ["关键实体"]
    }}
  ]
}}

## 大纲设计要求

1. **标题要精准、学术化**：不要使用「大背景」「核心分析」等泛泛标题。每个标题应直接反映该章节的核心内容。
2. **章节数量（强制）**：必须生成 4-6 个 sections。禁止只生成 1-2 个章节。每个 section 对应综述的一个独立主题方向。如果某方面研究成果丰富，可拆为两章；如果某一方向尚不成熟，合并或精简。
3. **每章应有明确的核心论点**：不要写成"介绍A、B、C方法"，而是有分析逻辑的论述方向。
4. **字数分配合理**：核心论述章节（通常 2-3 章）占总字数 60% 以上。
5. **综合优先于列举**：每个章节的 description 必须明确指出综合方式（对比/归纳/演进/分类），而非简单描述为"介绍XX方法"。例如：
   - "对比三类主流方法在精度与效率上的权衡，分析各自适用场景"
   - "归纳该领域从手工特征到端到端学习的演进趋势"
   - 禁止："介绍A方法、B方法、C方法"这类罗列式描述"""

    # 构建社区摘要段落（如果模板不包含占位符则追加到末尾）
    community_block = ""
    if community_context:
        community_block = f"\n\n## 社区摘要（各聚类关键发现与代表性方法）\n{community_context}\n"

    # 如果模板包含 {community_summaries} 占位符则替换，否则在 kg_summary 后追加
    if "{community_summaries}" in outline_prompt_template:
        prompt = outline_prompt_template.format(
            topic=topic,
            cluster_stats=clusters_context,
            kg_summary=kg_context,
            community_summaries=community_block,
        )
    else:
        prompt = outline_prompt_template.format(
            topic=topic,
            cluster_stats=clusters_context,
            kg_summary=kg_context,
        )
        # 在聚类统计后插入社区摘要
        if community_block:
            prompt = prompt.replace(
                "## 知识图谱摘要",
                f"{community_block}\n## 知识图谱摘要",
            )

    # 注入层次分类指导（在社区摘要之后、知识图谱摘要之前）
    if layer_guidance_block:
        prompt = prompt.replace(
            "## 知识图谱摘要",
            f"{layer_guidance_block}\n\n## 知识图谱摘要",
        )

    messages = [
        SystemMessage(content=(
            "你是一位精通学术写作的综述专家。请基于提供的聚类和知识图谱数据生成大纲。所有标题和描述必须使用中文。\n\n"
            "关键原则：综述是综合分析，不是文献堆叠。每个章节的 description 必须体现主题式的分析逻辑，"
            "而非逐篇介绍论文。大纲应为后续写作奠定'综合优先于列举'的基调——"
            "每个 section 的核心论点应围绕机制/方法/结论的对比或归纳展开，而非罗列各论文的发现。\n\n"
            "层次结构指导：聚类已按研究演进阶段分为 Foundation（基础层）、Development（发展层）、Frontier（前沿层）三层。"
            "请据此安排章节顺序：Foundation 层聚类对应综述前部（研究背景、经典方法），"
            "Development 层聚类对应综述中部（技术演进、方法对比），"
            "Frontier 层聚类对应综述后部（前沿方向、未来展望）。"
        )),
        HumanMessage(content=prompt),
    ]

    response = await _ainvoke_with_retry(
        agent,
        messages,
        timeout_s=DEFAULT_OUTLINE_TIMEOUT_S,
    )

    # LLM 响应 content 可能是 list（多模态格式）或 string
    raw_content = response.content
    if isinstance(raw_content, list):
        raw_content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in raw_content
        )

    try:
        outline = json.loads(raw_content)
    except json.JSONDecodeError:
        # 去掉 markdown 代码块
        content = raw_content.replace("```json", "").replace("```", "").strip()
        try:
            outline = json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 JSON 对象（从第一个 { 到最后一个 }）
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end > start:
                try:
                    outline = json.loads(content[start:end + 1])
                except json.JSONDecodeError:
                    # JSON 被截断：尝试修复不完整的 JSON
                    outline = _try_repair_truncated_json(content[start:])
            else:
                logger.error("Failed to parse outline response", response=raw_content[:500])
                raise ValueError(f"LLM returned invalid JSON for outline: {raw_content[:200]}")

    # 验证大纲：至少 3 个章节，否则使用 fallback
    sections = outline.get("sections", [])
    if len(sections) < 3:
        logger.warning(
            "LLM returned too few sections, using fallback outline",
            section_count=len(sections),
        )
        from ..graphs.nodes.outline_generation import _default_outline
        outline = _default_outline(topic)

    return outline


def _try_repair_truncated_json(content: str) -> dict:
    """
    尝试修复被 LLM 截断的 JSON。

    常见截断模式：
    1. 字符串未关闭：  "title": "xxx   → 补 "
    2. 数组未关闭：    "sections": [{...}, {  → 移除不完整元素，补 ]
    3. 对象未关闭：    {...                 → 补 }
    """
    import re

    # 逐步截断到最近的完整 JSON 结构
    # 先找到所有完整的 section 对象
    sections = []
    # 匹配完整的 section 块：{ "name": "...", "title": "...", ... }
    section_pattern = re.compile(
        r'\{\s*"name"\s*:\s*"([^"]+)"\s*,\s*"title"\s*:\s*"([^"]+)"'
        r'(?:\s*,\s*"description"\s*:\s*"([^"]*)")?'
        r'(?:\s*,\s*"target_words"\s*:\s*(\d+))?'
        r'(?:\s*,\s*"key_clusters"\s*:\s*\[([^\]]*)\])?'
        r'(?:\s*,\s*"key_entities"\s*:\s*\[([^\]]*)\])?'
        r'\s*\}',
        re.DOTALL,
    )

    # 提取 title
    title_match = re.search(r'"title"\s*:\s*"([^"]+)"', content)
    review_title = title_match.group(1) if title_match else "综述"

    for m in section_pattern.finditer(content):
        section = {
            "name": m.group(1),
            "title": m.group(2),
        }
        if m.group(3):
            section["description"] = m.group(3)
        if m.group(4):
            section["target_words"] = int(m.group(4))
        if m.group(5):
            try:
                section["key_clusters"] = [int(x.strip()) for x in m.group(5).split(",") if x.strip()]
            except ValueError:
                section["key_clusters"] = []
        if m.group(6):
            try:
                section["key_entities"] = [
                    x.strip().strip('"') for x in m.group(6).split(",") if x.strip()
                ]
            except Exception:
                section["key_entities"] = []
        sections.append(section)

    if sections:
        logger.warning(
            "Repaired truncated JSON outline",
            original_length=len(content),
            recovered_sections=len(sections),
        )
        return {"title": review_title, "sections": sections}

    # 如果正则也没法提取，直接报错
    logger.error("Failed to repair truncated JSON", content_preview=content[:500])
    raise ValueError(f"LLM returned invalid JSON for outline: {content[:200]}")


async def write_section(
    topic: str,
    review_title: str,
    section_plan: dict,
    cluster_data: str,
    sample_papers: str,
    references: str,
    evidence_cards: list[dict] | None = None,
    community_context: str | None = None,
    evidence_limitations: str | None = None,
    section_outline: dict | None = None,
    prev_summary: str = "",
    next_outline: dict | None = None,
) -> str:
    """
    撰写一个章节（对齐 Rust 版 write_section_user_with_communities）

    注入 community_context（社区上下文摘要）和 evidence_limitations（证据局限性），
    帮助 LLM 写出更有深度和准确性的章节。

    Args:
        topic: 研究主题
        review_title: 综述标题
        section_plan: 章节计划
        cluster_data: 聚类数据
        sample_papers: 样本论文
        references: 该章节分配的参考文献列表（局部编号）
        evidence_cards: 该章节相关的证据卡片
        community_context: 社区上下文摘要（对齐 Rust 版 render_section_community_context）
        evidence_limitations: 证据局限性说明（对齐 Rust 版 render_section_evidence_limitations）
        section_outline: 来自 section_outline_planner 的段落规划
        prev_summary: 前序 section 的核心论点摘要
        next_outline: 后序 section 的大纲信息

    Returns:
        章节内容
    """
    (
        cluster_data,
        sample_papers,
        references,
        community_context,
        evidence_limitations,
        evidence_cards,
    ) = _compact_section_inputs(
        cluster_data=cluster_data,
        sample_papers=sample_papers,
        references=references,
        community_context=community_context,
        evidence_limitations=evidence_limitations,
        evidence_cards=evidence_cards,
    )
    agent = create_writing_agent(temperature=0.7)

    # 注入 community context 和 evidence limitations 到 cluster_data
    # 对齐 Rust 版 append_optional_block / append_review_context_block
    enriched_cluster_data = cluster_data
    if community_context:
        enriched_cluster_data += f"\n\n## community_context\n{community_context}"
    if evidence_limitations:
        enriched_cluster_data += f"\n\n## evidence_limitations\n{evidence_limitations}"

    # 构建证据卡片上下文
    evidence_context = ""
    if evidence_cards:
        ec_lines = []
        for i, card in enumerate(evidence_cards[:10], 1):
            title = card.get("title", card.get("paper_title", ""))
            claim = card.get("claim", card.get("key_finding", ""))
            span = card.get("evidence_span", "")
            method = card.get("method", "")
            line = f"{i}. {title}"
            if claim:
                line += f" — {claim}"
            if span:
                line += f" (evidence: {span[:100]})"
            ec_lines.append(line)
        evidence_context = "\n".join(ec_lines)

    # 构建段落规划上下文
    section_outline_context = ""
    if section_outline:
        core_question = section_outline.get("core_question", "")
        narrative_arc = section_outline.get("narrative_arc", "")
        paragraphs = section_outline.get("paragraphs", [])
        transition_from_prev = section_outline.get("transition_from_prev", "自然切入")
        transition_to_next = section_outline.get("transition_to_next", "总结本节")

        outline_lines = ["## 本章节段落规划"]
        if core_question:
            outline_lines.append(f"核心问题：{core_question}")
        if narrative_arc:
            outline_lines.append(f"论述逻辑：{narrative_arc}")
        outline_lines.append("")
        if paragraphs:
            outline_lines.append("段落安排：")
            for p in paragraphs:
                idx = p.get("index", "")
                target = p.get("target_words", "")
                direction = p.get("direction", "")
                synthesis = p.get("synthesis_instruction", "")
                outline_lines.append(f"### 第 {idx} 段（约 {target} 字）")
                if direction:
                    outline_lines.append(f"方向：{direction}")
                if synthesis:
                    outline_lines.append(f"综合要求：{synthesis}")
                outline_lines.append("")
        outline_lines.append("衔接要求：")
        outline_lines.append(f"- 开头过渡：{transition_from_prev}")
        outline_lines.append(f"- 结尾铺垫：{transition_to_next}")
        section_outline_context = "\n".join(outline_lines)

    # 构建前文摘要上下文
    prev_summary_context = ""
    if prev_summary:
        prev_summary_context = f"## 前文摘要（已写内容，不要重复）\n{prev_summary}"

    # 构建后文预告上下文
    next_outline_context = ""
    if next_outline:
        next_title = next_outline.get("title", "")
        next_desc = next_outline.get("description", "")
        next_outline_context = f"## 后文预告\n下一节：{next_title} — {next_desc}"

    # 加载章节写作提示模板
    section_prompt_template = get_write_section_prompt()
    if not section_prompt_template:
        banned_block = format_banned_phrases_for_prompt()
        section_prompt_template = f"""你正在撰写一篇学术综述文章的一个章节。

## 研究主题
{{topic}}

## 综述标题
{{review_title}}

## 当前章节
章节名称: {{section_title}}
章节描述: {{section_description}}
目标字数: {{target_words}} 字

## 相关聚类数据
{{cluster_data}}

## 相关论文样本
{{sample_papers}}

## 真实可用的参考文献（只能从这里引用）
以下是从学术数据库中提取的真实论文，编号为本章节专用编号。请只引用以下列表中的论文，不得编造。

{{references}}

{{evidence_section}}

## 写作要求

### 学术风格
- 使用正式、严谨的学术中文
- 主动使用领域专业术语，体现对该领域的深入理解
- 句式应有变化：长短句结合，避免句式单一
- 段落之间要有逻辑推进关系，而非简单的并列

### 引用规范
- 每个关键论断必须有引用支撑
- 引用密度合理：段落中通常 2-4 处引用，但不要为凑引用而引用
- 当多篇文献支撑同一观点时合并引用 [1,2]；若不同文献有不同结论，用对比分析呈现
- 绝对禁止编造引用、作者、年份或期刊

### 论述要求
- 不仅要"综述"(列举已有工作)，更要"评论"(分析优劣、比较方法、揭示趋势)
- 展现领域内的**共识**与**争议**：哪些结论已被广泛接受？哪些仍在争论？
- 指出方法演进的**驱动力**：为什么从方法A演进到方法B？是因为精度不够？还是因为新数据类型出现？
- 如果不同研究之间存在结论冲突，明确写出并尝试分析原因

### 输出规范
- 直接输出章节正文（纯段落文本）
- 不要输出章节标题、不要输出参考文献列表、不要输出元说明
- 字数严格控制在 {{target_words}} 字左右，正负 20%。超出过多会被截断。

### 禁用表达
{banned_block}
每个段落应以实质性的分析判断或研究发现收尾，而非空洞的总结句。
用具体的分析逻辑（如"由于X限制，Y方法转向Z策略"）替代这些泛化短语。"""

    evidence_section = ""
    if evidence_context:
        evidence_section = f"""## 证据卡片（可引用的具体发现）
以下是与本章节相关的研究证据，可用于支撑论述：

{evidence_context}"""

    prompt = section_prompt_template.format(
        topic=topic,
        review_title=review_title,
        section_title=section_plan.get("title", ""),
        section_description=section_plan.get("description", ""),
        target_words=section_plan.get("target_words", 2000),
        cluster_data=enriched_cluster_data,
        sample_papers=sample_papers,
        references=references,
        evidence_section=evidence_section,
    )

    # 注入段落规划、前文摘要、后文预告到写作要求之前
    extra_context_blocks = []
    if section_outline_context:
        extra_context_blocks.append(section_outline_context)
    if prev_summary_context:
        extra_context_blocks.append(prev_summary_context)
    if next_outline_context:
        extra_context_blocks.append(next_outline_context)
    if extra_context_blocks:
        injection = "\n\n".join(extra_context_blocks) + "\n\n"
        prompt = prompt.replace("## 写作要求", f"{injection}## 写作要求")

    # 加载写作风格规范和结构指南（对齐 Rust 版 review_system）
    style_guide = get_review_style_prompt()
    structure_guide = get_review_structure_prompt()

    system_prompt = f"""You write grounded Chinese academic literature reviews using only supplied evidence.

Review structure guide:
{structure_guide}

Review style guide:
{style_guide}

Hard rules:
- Use only supplied papers and evidence.
- Do not invent references, authors, venues, years, DOI, or claims.
- Use IEEE-style [N] citations matching supplied evidence numbers.
- NEVER use author-year citations like (Friedman, 2024) or (Smith et al., 2023). Only [1], [1,2], [1-3] format.
- NEVER use paper_id (like p1, p2) as citation numbers. Only use the [N] numbers from the reference list.
- NEVER put citation-bearing prose inside parentheses, for example "（文献[24][28]已证实...）" or "([27][29])".
- **ABSOLUTELY FORBIDDEN**: Never start a sentence with "文献[N]" or use "文献[N]" as the subject of a sentence. Write the factual statement first and put [N] at the end.
- **FORBIDDEN**: "文献[42]指出...", "文献[43]通过...", "文献[52]的实验...", "文献[49]的数据..."
- **CORRECT**: "多尺度耦合计算中仍存在35%的算力浪费[42]。", "结合概率密度演化方程实现时序演化模拟[43]。"
- Citations must be part of the normal sentence syntax, for example "已有研究[24,28]证实..." or "该局限已在医疗与交通场景研究中得到讨论[27,29]".
- Merge adjacent citation tokens: write [24,28], never [24][28].
- Keep output as UTF-8 markdown.
- Avoid internal labels such as Cluster 0 or pipeline implementation details.
- Do NOT output a reference list or bibliography at the end of the section.
- Do NOT output meta-commentary like "(字数统计：1520字)" or "(以上为...)".
- Strictly adhere to the target word count (±20%).

SYNTHESIS-FIRST RULE (critical):
A literature review is NOT a collection of individual paper summaries. Each paragraph must be organized around a central thesis or analytical theme, with multiple papers serving as supporting evidence.
- BANNED PATTERN — paper-by-paper listing: "Author A [1] proposed X. Author B [2] proposed Y. Author C [3] proposed Z." This is a summary list, not a review.
- BANNED PATTERN — sequential paper introduction: Each sentence introduces a different paper's finding without analytical connection.
- REQUIRED PATTERN — thematic synthesis: "Two dominant paradigms have emerged for X: attention-based approaches [1,2] achieve Y through Z, while state-space models [3,4] trade precision for efficiency. The hybrid approach [5] attempts to bridge this gap, though at the cost of..."
- REQUIRED PATTERN — comparative analysis: "Although [1] and [3] both adopt strategy X, the former focuses on Y while the latter targets Z; this divergence stems from their different assumptions about..."
- When comparing research, explicitly state similarities, differences, and underlying reasons — never simply juxtapose findings.
- Organize paragraphs by mechanism, method category, or conclusion theme — not by individual papers."""

    # 输出卫生规则 + 引用约束补充（对齐 Rust 版 write_section_user 的额外约束）
    output_hygiene_rules = """## Output hygiene rules
- Treat related paper samples, evidence summary, claim, evidence_span, method, metric, limitation, confidence, reference candidates, citation candidates, cluster data, community context, and evidence_limitations as private working material only.
- Do not copy those labels or raw working-material blocks into the section.
- Output only polished section body paragraphs. Do not output a section title, reference list, bibliography, candidate list, evidence-card JSON, audit notes, or implementation details.
- Use only [N] citation numbers from the provided usable reference list, and cite a source only when it directly supports the sentence.
- The same [N] number must always refer to the same paper_id, title, and evidence_card_id shown in the related paper samples and usable reference list.
- Never cite a sentence with [N] if the claim was taken from another paper_id, even when both papers discuss a similar topic.
- Do not write parenthesized citation prose such as "（文献[24][28]已证实网络稳定性...）"; integrate the citation into the sentence instead.
- Merge adjacent citation tokens: write [24,28], never [24][28]."""

    citation_constraint_supplement = """## 引用约束补充
- 本章节必须使用本章节"真实可用的参考文献"列表中的 [N] 编号。
- 本章节会提供约 20-30 篇候选文献；请只选择真正支撑论点的文献，不要为了凑引用而引用。
- 每个 section 尽量使用 10-20 篇有证据支撑的文献；如果证据不足，可以少于 10 篇，但必须改写或删除无法被候选文献支撑的判断。
- 每一句包含事实判断、方法比较、指标、趋势、局限或结论的句子，都必须能被同句或邻近句中的 [N] 文献支撑。
- 如果同一论文支撑多个判断，可以重复引用，但不得引用列表外编号。
- 不能编造引用、作者、年份、期刊、DOI 或论文结论。
- **引用格式强制**：只使用 [N] 数字编号。禁止 (Author, Year) 格式。禁止使用 paper_id 作为引用号。
- **禁止括号化引用说明**：不要写"（文献[24][28]已证实...）"、"（[27][29]）"、"([x])"、"([1][2])"。引用必须进入正文句法，例如"已有研究[24,28]证实..."、"这种局限在医疗与交通场景中已有讨论[27,29]"。
- **禁止相邻引用块**：不要写 [24][28]，合并为 [24,28]。"""

    # 在写作要求之后插入 output hygiene rules 和引用约束
    prompt = prompt.replace(
        "## 写作要求",
        f"{output_hygiene_rules}\n\n{citation_constraint_supplement}\n\n## 写作要求",
    )

    # 注入段落规划 + 上下文链（来自 section_outline_planner）
    if section_outline:
        outline_parts = []
        core_q = section_outline.get("core_question", "")
        arc = section_outline.get("narrative_arc", "")
        if core_q:
            outline_parts.append(f"核心问题：{core_q}")
        if arc:
            outline_parts.append(f"论述逻辑：{arc}")

        paragraphs = section_outline.get("paragraphs", [])
        if paragraphs:
            outline_parts.append("\n段落安排：")
            for p in paragraphs:
                idx = p.get("index", 0)
                direction = p.get("direction", "")
                pw = p.get("target_words", "")
                synth = p.get("synthesis_instruction", "")
                line = f"### 第 {idx} 段（约 {pw} 字）\n方向：{direction}"
                if synth:
                    line += f"\n综合要求：{synth}"
                outline_parts.append(line)

        trans_prev = section_outline.get("transition_from_prev", "")
        trans_next = section_outline.get("transition_to_next", "")
        if trans_prev:
            outline_parts.append(f"\n开头过渡方向：{trans_prev}")
        if trans_next:
            outline_parts.append(f"结尾铺垫方向：{trans_next}")

        already = section_outline.get("already_covered", [])
        if already:
            outline_parts.append(f"\n前序已覆盖（不要重复）：{'; '.join(already)}")

        section_outline_block = "\n".join(outline_parts)
        prompt = prompt.replace(
            "## 写作要求",
            f"## 本章节段落规划\n{section_outline_block}\n\n## 写作要求",
        )

    if prev_summary:
        prompt = prompt.replace(
            "## 写作要求",
            f"## 前文摘要（已写内容，不要重复）\n{prev_summary}\n\n## 写作要求",
        )

    if next_outline:
        next_title = next_outline.get("title", "")
        next_desc = next_outline.get("description", "")
        if next_title:
            prompt = prompt.replace(
                "## 写作要求",
                f"## 后文预告\n下一节：{next_title} — {next_desc}\n请在结尾为此做铺垫。\n\n## 写作要求",
            )

    if len(prompt) > _WRITING_CONTEXT_CHAR_BUDGET:
        prompt = _clip_text_block(prompt, _WRITING_CONTEXT_CHAR_BUDGET)
    agent = create_writing_agent(
        temperature=0.7,
        max_tokens=_writing_max_tokens_for_prompt(prompt),
    )

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt),
    ]

    try:
        response = await _ainvoke_with_retry(
            agent,
            messages,
            timeout_s=DEFAULT_SECTION_WRITE_TIMEOUT_S,
        )
    except Exception as e:
        logger.error(
            "Section writing failed, using fallback text",
            section_title=section_plan.get("title", ""),
            error=str(e),
        )
        return _fallback_section_text(section_plan, references, evidence_cards)

    # LLM 响应 content 可能是 list（多模态格式）或 string
    content = response.content
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return content


def _coerce_llm_text(content) -> str:
    if isinstance(content, list):
        return "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return str(content or "")


def _as_single_unit(text: str) -> str:
    lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#") or line.startswith("- ") or re.match(r"^\d+[.)]\s+", line):
            continue
        if line.lower().startswith(("references", "bibliography")):
            break
        lines.append(line)
    return " ".join(lines).strip()


def _unit_outline(section_outline: dict, paragraph: dict) -> dict:
    outline = dict(section_outline or {})
    outline["paragraphs"] = [paragraph]
    return outline


def _next_unit_hint(paragraphs: list[dict], index: int, next_outline: dict | None) -> dict | None:
    if index + 1 < len(paragraphs):
        para = paragraphs[index + 1]
        return {
            "title": f"next paragraph {para.get('index', index + 2)}",
            "description": "; ".join(
                part for part in [
                    f"task_type={para.get('task_type', '')}",
                    str(para.get("direction", "")),
                    str(para.get("synthesis_instruction", "")),
                ]
                if part
            ),
        }
    return next_outline


async def refine_section_units_local_coherence(
    units: list[str],
    section_outline: dict,
    references: str,
) -> list[str]:
    """
    AutoSurvey-style local coherence enhancement over paragraph/subsection units.

    The refinement is intentionally local: each call sees previous/current/next
    only and must preserve citation numbers.
    """
    if len(units) <= 1:
        return units

    agent = create_writing_agent(temperature=0.3)
    paragraphs = section_outline.get("paragraphs", []) if section_outline else []
    refined = list(units)

    async def _refine_at(i: int) -> None:
        para_plan = paragraphs[i] if i < len(paragraphs) else {}
        prompt = f"""Refine only the CURRENT paragraph of a Chinese academic review.

Rules:
- Return only the revised CURRENT paragraph, no heading, no list, no notes.
- Preserve all valid [N] citation numbers already present unless a sentence is removed.
- Do not add citations outside the usable reference list.
- Rewrite any parenthesized citation prose such as "（文献[24][28]已证实...）" into normal sentence syntax.
- Merge adjacent citation tokens such as [24][28] into [24,28].
- Improve local transition, remove redundancy, and keep the paragraph's single task.
- Do not merge with previous or next paragraph.

Paragraph plan:
task_type: {para_plan.get('task_type', '')}
direction: {para_plan.get('direction', '')}
synthesis_instruction: {para_plan.get('synthesis_instruction', '')}
target_words: {para_plan.get('target_words', '')}

Usable references:
{references}

PREVIOUS paragraph:
{refined[i - 1] if i > 0 else ''}

CURRENT paragraph:
{refined[i]}

NEXT paragraph:
{refined[i + 1] if i + 1 < len(refined) else ''}
"""
        response = await _ainvoke_with_retry(
            agent,
            [
                SystemMessage(content="You are a strict academic prose editor. Preserve evidence grounding and numeric citations."),
                HumanMessage(content=prompt),
            ],
            max_retries=2,
            timeout_s=DEFAULT_SECTION_REFINE_TIMEOUT_S,
        )
        candidate = _as_single_unit(_coerce_llm_text(response.content))
        if candidate:
            refined[i] = candidate

    for start in (0, 1):
        for idx in range(start, len(refined), 2):
            await _refine_at(idx)

    return refined


async def write_section_units(
    topic: str,
    review_title: str,
    section_plan: dict,
    cluster_data: str,
    sample_papers: str,
    references: str,
    evidence_cards: list[dict] | None = None,
    community_context: str | None = None,
    evidence_limitations: str | None = None,
    section_outline: dict | None = None,
    prev_summary: str = "",
    next_outline: dict | None = None,
) -> str:
    """
    Write a section as paragraph/subsection units instead of one monolithic call.
    """
    paragraphs = list((section_outline or {}).get("paragraphs") or [])
    if not paragraphs:
        return await write_section(
            topic=topic,
            review_title=review_title,
            section_plan=section_plan,
            cluster_data=cluster_data,
            sample_papers=sample_papers,
            references=references,
            evidence_cards=evidence_cards,
            community_context=community_context,
            evidence_limitations=evidence_limitations,
            section_outline=section_outline,
            prev_summary=prev_summary,
            next_outline=next_outline,
        )

    (
        compact_cluster_data,
        compact_sample_papers,
        compact_references,
        compact_community_context,
        compact_evidence_limitations,
        compact_evidence_cards,
    ) = _compact_section_inputs(
        cluster_data=cluster_data,
        sample_papers=sample_papers,
        references=references,
        community_context=community_context,
        evidence_limitations=evidence_limitations,
        evidence_cards=evidence_cards,
    )

    units: list[str] = []
    for idx, paragraph in enumerate(paragraphs):
        unit_plan = dict(section_plan)
        unit_plan["target_words"] = paragraph.get(
            "target_words",
            max(250, int(section_plan.get("target_words", 1500) / max(len(paragraphs), 1))),
        )
        unit_plan["description"] = " ".join(
            part for part in [
                str(section_plan.get("description", "")),
                f"Current writing unit task_type={paragraph.get('task_type', '')}.",
                str(paragraph.get("direction", "")),
                str(paragraph.get("synthesis_instruction", "")),
            ]
            if part
        )

        unit_prev = prev_summary
        if units:
            unit_prev = f"{prev_summary}\n\nAlready written paragraphs in this section (DO NOT repeat these):\n" + "\n\n".join(units)

        try:
            raw_unit = await write_section(
                topic=topic,
                review_title=review_title,
                section_plan=unit_plan,
                cluster_data=compact_cluster_data,
                sample_papers=compact_sample_papers,
                references=compact_references,
                evidence_cards=compact_evidence_cards,
                community_context=compact_community_context,
                evidence_limitations=compact_evidence_limitations,
                section_outline=_unit_outline(section_outline or {}, paragraph),
                prev_summary=unit_prev,
                next_outline=_next_unit_hint(paragraphs, idx, next_outline),
            )
        except Exception as e:
            logger.error(
                "Paragraph unit writing failed, using fallback text",
                section_title=section_plan.get("title", ""),
                paragraph_index=idx + 1,
                error=str(e),
            )
            raw_unit = _fallback_section_text(unit_plan, compact_references, compact_evidence_cards)
        unit_text = _as_single_unit(_coerce_llm_text(raw_unit))
        if not unit_text:
            raise ValueError(f"Paragraph unit {idx + 1} produced empty content")
        units.append(unit_text)

    if _should_refine_section_units():
        units = await refine_section_units_local_coherence(units, section_outline or {}, references)
    else:
        logger.info(
            "Skipped optional section unit coherence refinement",
            unit_count=len(units),
            env=_REFINE_SECTION_UNITS_ENV,
        )
    return "\n\n".join(unit for unit in units if unit.strip())


async def revise_section(
    section_content: str,
    feedback: str,
    papers_context: str,
) -> str:
    """
    根据反馈修订章节

    Args:
        section_content: 原始章节内容
        feedback: 反馈信息
        papers_context: 相关论文上下文

    Returns:
        修订后的章节内容
    """
    agent = create_writing_agent()

    prompt = f"""请根据以下反馈修订章节内容：

原始内容：
{section_content}

反馈：
{feedback}

可用论文：
{papers_context}

请输出修订后的完整章节内容。"""

    messages = [
        SystemMessage(content="你是一个学术写作修订专家。"),
        HumanMessage(content=prompt),
    ]

    try:
        response = await _ainvoke_with_retry(agent, messages, timeout_s=DEFAULT_WRITING_TIMEOUT_S)
    except Exception as e:
        logger.error("Legacy section revision failed, returning original content", error=str(e))
        return section_content

    # LLM 响应 content 可能是 list（多模态格式）或 string
    content = response.content
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return content


# =============================================================================
# 组装综述（对齐 Rust 版 assemble_review）
# =============================================================================

def render_section_community_context(
    section_plan: dict,
    clusters: list[dict],
    papers: list[dict],
    evidence_cards: list[dict] | None = None,
    kg_entities: list[dict] | None = None,
) -> str:
    """
    渲染章节的社区上下文摘要（对齐 Rust 版 render_section_community_context）。

    为每个章节的关键聚类生成简要摘要，帮助 LLM 理解社区结构。
    包含：论文数、代表性论文、top entities、关键发现。
    """
    key_clusters = section_plan.get("target_communities") or section_plan.get("key_clusters", [])
    if not key_clusters:
        return ""

    parts = []
    paper_map = {p.get("id"): p for p in papers}
    paper_set_all = {p.get("id") for p in papers}

    # 构建 paper_id -> entity names 映射
    entity_by_paper: dict[str, list[str]] = {}
    if kg_entities:
        for ent in kg_entities:
            for pid in ent.get("paper_ids", []):
                entity_by_paper.setdefault(pid, []).append(ent.get("name", ""))

    for cid in key_clusters:
        cluster = next((c for c in clusters if str(c.get("id")) == str(cid)), None)
        if not cluster:
            continue

        cluster_papers = cluster.get("paper_ids", [])
        cluster_paper_set = set(cluster_papers)
        size = len(cluster_papers)

        # 提取代表性论文标题
        sample_titles = []
        for pid in cluster_papers[:5]:
            p = paper_map.get(pid)
            if p:
                sample_titles.append(p.get("title", ""))

        # 提取 top entities（对齐 Rust 版 top_entities）
        entity_counts: dict[str, int] = {}
        for pid in cluster_papers:
            for ename in entity_by_paper.get(pid, []):
                entity_counts[ename] = entity_counts.get(ename, 0) + 1
        top_entities = sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)[:8]
        entity_str = ", ".join(f"{name}({cnt})" for name, cnt in top_entities)

        # 提取该社区的 evidence cards
        cluster_evidence = []
        if evidence_cards:
            for card in evidence_cards:
                card_pid = card.get("paper_id", "")
                if card_pid in cluster_paper_set:
                    claim = card.get("claim", card.get("key_finding", ""))
                    if claim:
                        cluster_evidence.append(claim)

        line = f"community {cid}: papers={size}"
        if sample_titles:
            line += f"; representatives={'; '.join(sample_titles[:3])}"
        if entity_str:
            line += f"; top_entities={entity_str}"
        if cluster_evidence:
            line += f"; key_findings={'; '.join(cluster_evidence[:3])}"
        parts.append(line)

    return "\n".join(parts) if parts else ""


def render_section_evidence_limitations(
    section_plan: dict,
    evidence_cards: list[dict] | None = None,
) -> str:
    """
    渲染证据局限性说明（对齐 Rust 版 render_section_evidence_limitations）。

    指出该章节证据的局限性，帮助 LLM 在写作中更准确地表述。
    """
    if not evidence_cards:
        return ""

    # 统计低置信度证据
    low_confidence = []
    for card in evidence_cards:
        conf = card.get("confidence", 1.0)
        if isinstance(conf, str):
            try:
                conf = float(conf)
            except ValueError:
                conf = 1.0
        if conf < 0.5:
            title = card.get("title", card.get("paper_title", ""))
            low_confidence.append(f"{title} (confidence={conf:.2f})")

    if not low_confidence:
        return ""

    return (
        "Evidence limitations for this section:\n"
        + "\n".join(f"- {lc}" for lc in low_confidence[:5])
        + "\nNote: Low-confidence evidence should be cited with appropriate hedging language."
    )


async def assemble_review(
    topic: str,
    review_title: str,
    sections: list[dict],
    references: str,
    citation_style: str = "IEEE",
) -> str:
    """
    拼装综述（对齐 Rust 版 assemble_review_user）。

    1. 确定性拼装：按顺序拼接各章节
    2. LLM 审计：使用 assemble_review prompt 检查风格一致性

    Args:
        topic: 研究主题
        review_title: 综述标题
        sections: 章节列表，每个含 "title" 和 "content"
        references: 参考文献列表
        citation_style: 引用格式

    Returns:
        完整的综述 markdown
    """
    # 确定性拼装（对齐 Rust 版 assemble_review_deterministic）
    section_parts = []
    for sec in sections:
        title = sec.get("title", "")
        content = sec.get("content", "")
        section_parts.append(f"## {title}\n\n{content}")

    deterministic_md = f"# {review_title}\n\n" + "\n\n".join(section_parts)

    # 如果有参考文献，追加
    if references:
        deterministic_md += f"\n\n## References\n\n{references}"

    logger.info(
        "Using deterministic assembly",
        policy="llm_assembly_disabled_final_uses_deterministic_markdown",
    )
    return deterministic_md
