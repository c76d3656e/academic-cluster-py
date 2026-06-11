"""
写作 Agent

负责生成综述内容，包括大纲、章节和引用。
参考 Rust 版本的 prompt 设计，提供高质量的学术写作指导。
"""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from ..prompts import (
    get_generate_outline_prompt,
    get_review_style_prompt,
    get_write_section_prompt,
)

logger = structlog.get_logger()


async def _ainvoke_with_retry(agent, messages, max_retries=3):
    """带重试的 LLM 调用"""
    @retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=2, min=3, max=30),
        reraise=True,
    )
    async def _call():
        return await agent.ainvoke(messages)

    return await _call()


# =============================================================================
# Agent 创建
# =============================================================================

def create_writing_agent(
    model: str | None = None,
    temperature: float = 0.7,
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

    llm = create_llm(temperature=temperature, max_tokens=8192)
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
    total_target_words: int = 12000,
) -> dict:
    """
    生成综述大纲

    Args:
        topic: 研究主题
        clusters: 聚类信息列表
        kg_summary: 知识图谱摘要
        evidence_cards: 证据卡片列表
        total_target_words: 总目标字数

    Returns:
        大纲数据
    """
    agent = create_writing_agent()

    # 构建聚类统计上下文（对齐 Rust 版 render_cluster_stats）
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
        line = f"cluster {i}: {cluster_size} papers"
        if entity_str:
            line += f"; entities: {entity_str}"
        clusters_context_parts.append(line)
    clusters_context = "\n".join(clusters_context_parts) if clusters_context_parts else "暂无聚类数据"

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

    # 加载大纲生成提示模板
    outline_prompt_template = get_generate_outline_prompt()
    if not outline_prompt_template:
        outline_prompt_template = """你是一位精通学术写作的综述专家。请基于以下聚类分析结果和知识图谱数据，生成一份综述文章的详细大纲。

研究主题: {topic}

## 聚类统计（Cluster Stats）
{cluster_stats}

## 知识图谱摘要（关键实体和关系）
{kg_summary}

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

1. **总字数目标**：整篇综述目标 {total_target_words} 字。各章 target_words 之和应接近此目标。
2. **标题要精准、学术化**：不要使用「大背景」「核心分析」等泛泛标题。每个标题应直接反映该章节的核心内容。
3. **章节数量**：生成 5-8 章。如果某方面研究成果丰富，可拆为两章；如果某一方向尚不成熟，合并或精简。
4. **每章应有明确的核心论点**：不要写成"介绍A、B、C方法"，而是有分析逻辑的论述方向。
5. **字数分配合理**：核心论述章节（通常 2-3 章）占总字数 60% 以上，每章 target_words 不低于 1200。"""

    prompt = outline_prompt_template.format(
        topic=topic,
        cluster_stats=clusters_context,
        kg_summary=kg_context,
        total_target_words=total_target_words,
    )

    messages = [
        SystemMessage(content="你是一位精通学术写作的综述专家。请基于提供的聚类和知识图谱数据生成大纲。"),
        HumanMessage(content=prompt),
    ]

    response = await _ainvoke_with_retry(agent, messages)

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
        content = raw_content.replace("```json", "").replace("```", "").strip()
        try:
            outline = json.loads(content)
        except json.JSONDecodeError:
            logger.error("Failed to parse outline response", response=raw_content[:500])
            raise ValueError(f"LLM returned invalid JSON for outline: {raw_content[:200]}")

    return outline


async def write_section(
    topic: str,
    review_title: str,
    section_plan: dict,
    cluster_data: str,
    sample_papers: str,
    references: str,
    evidence_cards: list[dict] | None = None,
) -> str:
    """
    撰写一个章节

    Args:
        topic: 研究主题
        review_title: 综述标题
        section_plan: 章节计划
        cluster_data: 聚类数据
        sample_papers: 样本论文
        references: 该章节分配的参考文献列表（局部编号）
        evidence_cards: 该章节相关的证据卡片

    Returns:
        章节内容
    """
    agent = create_writing_agent(temperature=0.7)

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

    # 加载章节写作提示模板
    section_prompt_template = get_write_section_prompt()
    if not section_prompt_template:
        section_prompt_template = """你正在撰写一篇学术综述文章的一个章节。

## 研究主题
{topic}

## 综述标题
{review_title}

## 当前章节
章节名称: {section_title}
章节描述: {section_description}
目标字数: {target_words} 字

## 相关聚类数据
{cluster_data}

## 相关论文样本
{sample_papers}

## 真实可用的参考文献（只能从这里引用）
以下是从学术数据库中提取的真实论文，编号为本章节专用编号。请只引用以下列表中的论文，不得编造。

{references}

{evidence_section}

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
- 字数控制在 {target_words} 字左右，正负 20%"""

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
        cluster_data=cluster_data,
        sample_papers=sample_papers,
        references=references,
        evidence_section=evidence_section,
    )

    # 加载写作风格规范
    style_guide = get_review_style_prompt()

    messages = [
        SystemMessage(content=f"""你是一位精通学术写作的综述专家。请严格按照以下写作规范撰写章节：

{style_guide}

关键要求：
1. 只使用连贯段落，严禁分点列表
2. 禁止出现聚类标记（Cluster 0, Cluster 1等）
3. 禁止口语化表达
4. 使用IEEE引用格式 [1], [2], [1,2]
5. 正文不使用markdown标题"""),
        HumanMessage(content=prompt),
    ]

    response = await _ainvoke_with_retry(agent, messages)

    # LLM 响应 content 可能是 list（多模态格式）或 string
    content = response.content
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return content


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

    response = await _ainvoke_with_retry(agent, messages)

    # LLM 响应 content 可能是 list（多模态格式）或 string
    content = response.content
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    return content
