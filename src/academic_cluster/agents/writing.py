"""
写作 Agent

负责生成综述内容，包括大纲、章节和引用。
这是最复杂的 Agent，需要：
- 理解聚类结构和知识图谱
- 生成连贯的学术文本
- 正确引用论文
- 遵循学术写作规范
"""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI

from ..config import get_settings

logger = structlog.get_logger()


# =============================================================================
# Tools - 被写作 Agent 调用的工具
# =============================================================================

@tool
def get_paper_details(paper_id: str) -> dict:
    """
    获取论文详情

    从数据库获取论文的完整信息，包括标题、摘要、作者、引用等。
    """
    # TODO: 从数据库获取
    # 这是一个占位实现
    return {
        "id": paper_id,
        "title": "论文标题",
        "abstract": "论文摘要",
        "authors": [],
        "year": 2024,
        "citation_count": 0,
    }


@tool
def format_citation(paper_id: str, style: str = "apa") -> str:
    """
    格式化论文引用

    Args:
        paper_id: 论文 ID
        style: 引用格式 (apa, ieee, mla, chicago)

    Returns:
        格式化的引用字符串
    """
    # TODO: 从数据库获取论文并格式化
    # 这是一个占位实现
    return f"[{paper_id}] Author. (2024). Title. Journal."


@tool
def get_cluster_summary(cluster_id: str) -> dict:
    """
    获取聚类摘要

    返回聚类的主要主题、关键实体和代表性论文。
    """
    # TODO: 从数据库获取
    return {
        "id": cluster_id,
        "name": "聚类名称",
        "main_topics": ["主题1", "主题2"],
        "key_entities": ["实体1", "实体2"],
        "size": 10,
    }


@tool
def validate_citations(text: str, valid_paper_ids: list[str]) -> dict:
    """
    验证文本中的引用是否有效

    检查所有 [N] 格式的引用是否对应有效的论文 ID。

    Returns:
        {
            "valid": bool,
            "invalid_citations": list[str],
            "total_citations": int
        }
    """
    import re

    # 提取所有引用标记
    citation_pattern = r'\[(\d+)\]'
    citations = re.findall(citation_pattern, text)

    # 检查有效性（简化版本）
    invalid = []
    for cite in citations:
        # TODO: 实际应该检查引用映射
        pass

    return {
        "valid": len(invalid) == 0,
        "invalid_citations": invalid,
        "total_citations": len(citations),
    }


# =============================================================================
# 提示模板
# =============================================================================

OUTLINE_SYSTEM_PROMPT = """你是一个学术综述大纲规划专家。基于研究主题、论文聚类和知识图谱，生成一个结构化的综述大纲。

大纲应该包括：
1. 引言：研究背景和综述范围
2. 方法论：文献搜索和筛选方法
3. 主体章节：每个主要研究方向一个章节
4. 讨论：研究趋势和未来方向
5. 结论：总结和展望

每个章节应该：
- 有清晰的标题和描述
- 关联到相关的论文聚类
- 列出关键要点
- 指定目标字数

输出格式（严格 JSON）：
{
  "title": "综述标题",
  "abstract": "综述摘要",
  "sections": [
    {
      "number": 1,
      "title": "章节标题",
      "description": "章节描述",
      "key_points": ["要点1", "要点2"],
      "cluster_ids": ["cluster_1", "cluster_2"],
      "target_word_count": 2000
    }
  ]
}
"""


SECTION_SYSTEM_PROMPT = """你是一个学术写作专家。请根据以下信息撰写综述的一个章节。

要求：
1. 使用学术语言和正式风格
2. 合理引用提供的论文
3. 使用 [N] 格式引用论文（N 是引用编号）
4. 保持逻辑连贯和段落结构
5. 达到目标字数
6. 不要编造不存在的信息

章节信息：
- 标题: {title}
- 描述: {description}
- 关键要点: {key_points}
- 目标字数: {target_word_count}

可用论文：
{papers_context}

请直接输出章节内容，不需要额外说明。
"""


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
        绑定了工具的 LLM 实例
    """
    settings = get_settings()

    if model is None:
        model = settings.writing.model

    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=settings.llm.api_key,
        base_url=settings.llm.base_url,
    )

    # 绑定工具
    agent = llm.bind_tools([
        get_paper_details,
        format_citation,
        get_cluster_summary,
        validate_citations,
    ])

    logger.info("Writing agent created", model=model)

    return agent


# =============================================================================
# 写作函数
# =============================================================================

async def generate_outline(
    topic: str,
    clusters: list[dict],
    kg_summary: dict,
) -> dict:
    """
    生成综述大纲

    Args:
        topic: 研究主题
        clusters: 聚类信息列表
        kg_summary: 知识图谱摘要

    Returns:
        大纲数据
    """
    agent = create_writing_agent()

    # 构建上下文
    clusters_context = "\n".join([
        f"- 聚类 {c.get('id', i)}: {c.get('name', '未命名')} "
        f"(主题: {', '.join(c.get('main_topics', []))}, "
        f"论文数: {c.get('size', 0)})"
        for i, c in enumerate(clusters)
    ])

    kg_context = f"主要实体类型: {', '.join(kg_summary.get('entity_types', []))}"
    kg_context += f"\n主要关系类型: {', '.join(kg_summary.get('relation_types', []))}"

    prompt = f"""请为以下研究主题生成综述大纲：

研究主题: {topic}

论文聚类:
{clusters_context}

知识图谱摘要:
{kg_context}

请生成一个结构化的综述大纲。"""

    messages = [
        SystemMessage(content=OUTLINE_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    response = await agent.ainvoke(messages)

    try:
        outline = json.loads(response.content)
    except json.JSONDecodeError:
        content = response.content
        content = content.replace("```json", "").replace("```", "").strip()
        try:
            outline = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Failed to parse outline response")
            outline = {
                "title": f"{topic} - 文献综述",
                "abstract": "",
                "sections": [],
            }

    return outline


async def write_section(
    section_plan: dict,
    papers_context: str,
) -> str:
    """
    撰写一个章节

    Args:
        section_plan: 章节计划
        papers_context: 相关论文的上下文信息

    Returns:
        章节内容
    """
    agent = create_writing_agent()

    prompt = SECTION_SYSTEM_PROMPT.format(
        title=section_plan.get("title", ""),
        description=section_plan.get("description", ""),
        key_points=", ".join(section_plan.get("key_points", [])),
        target_word_count=section_plan.get("target_word_count", 1000),
        papers_context=papers_context,
    )

    messages = [
        SystemMessage(content="你是一个学术写作专家。"),
        HumanMessage(content=prompt),
    ]

    response = await agent.ainvoke(messages)

    return response.content


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

    response = await agent.ainvoke(messages)

    return response.content
