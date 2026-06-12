"""
证据生成 Agent

负责为论文生成结构化证据卡片。
"""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

logger = structlog.get_logger()


EVIDENCE_SYSTEM_PROMPT = """你是一个学术证据分析专家。你的任务是从学术论文中提取结构化的证据信息。

对于每篇论文，你需要生成一个证据卡片，包含：
- claim: 论文的核心主张或贡献
- evidence_span: 支持主张的关键证据片段（直接引用或摘要）
- method: 使用的主要方法
- metric: 使用的评估指标
- limitation: 论文提到的局限性
- confidence: 证据的置信度 (0-1)

输出格式（严格 JSON）：
{
  "claim": "核心主张",
  "evidence_span": "证据片段",
  "method": "使用方法",
  "metric": "评估指标",
  "limitation": "局限性",
  "confidence": 0.85
}
"""


EVIDENCE_PROMPT = """请分析以下论文并生成证据卡片。

标题: {title}
摘要: {abstract}
社区主题: {cluster_topics}

请以 JSON 格式输出。
"""


def create_evidence_agent(
    model: str | None = None,
    temperature: float = 0.2,
) -> ChatOpenAI:
    """创建证据生成 Agent"""
    from ..services.llm_client import create_llm
    return create_llm(temperature=temperature)


async def generate_evidence_card(
    paper: dict,
    cluster_topics: list[str] | None = None,
) -> dict:
    """
    为单篇论文生成证据卡片

    Args:
        paper: 论文信息，包含 title 和 abstract
        cluster_topics: 论文所属社区的主题

    Returns:
        证据卡片数据
    """
    agent = create_evidence_agent()

    prompt = EVIDENCE_PROMPT.format(
        title=paper.get("title", ""),
        abstract=paper.get("abstract", "无摘要"),
        cluster_topics=", ".join(cluster_topics) if cluster_topics else "未知",
    )

    messages = [
        SystemMessage(content=EVIDENCE_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    from ..services.llm_client import ainvoke_with_callbacks
    response = await ainvoke_with_callbacks(agent, messages)

    # LLM 响应 content 可能是 list（多模态格式）或 string
    raw_content = response.content
    if isinstance(raw_content, list):
        raw_content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in raw_content
        )

    try:
        result = json.loads(raw_content)
    except json.JSONDecodeError:
        # 去掉 markdown 代码块
        content = raw_content.replace("```json", "").replace("```", "").strip()
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            # 尝试提取 JSON 对象
            start = content.find("{")
            end = content.rfind("}")
            if start != -1 and end > start:
                try:
                    result = json.loads(content[start:end + 1])
                except json.JSONDecodeError:
                    logger.error("Failed to parse evidence response", response=raw_content[:500])
                    raise ValueError(f"LLM returned invalid JSON for evidence card: {raw_content[:200]}")
            else:
                logger.error("Failed to parse evidence response", response=raw_content[:500])
                raise ValueError(f"LLM returned invalid JSON for evidence card: {raw_content[:200]}")

    # 添加论文 ID
    result["paper_id"] = paper.get("id")

    return result


async def generate_evidence_cards_batch(
    papers: list[dict],
    cluster_topics: dict[str, list[str]] | None = None,
) -> list[dict]:
    """
    批量生成证据卡片

    Args:
        papers: 论文列表
        cluster_topics: 论文 ID 到社区主题的映射

    Returns:
        证据卡片列表
    """
    import asyncio

    if cluster_topics is None:
        cluster_topics = {}

    tasks = [
        generate_evidence_card(
            paper=paper,
            cluster_topics=cluster_topics.get(paper.get("id")),
        )
        for paper in papers
    ]

    results = await asyncio.gather(*tasks, return_exceptions=True)

    evidence_cards = []
    for result in results:
        if isinstance(result, Exception):
            logger.error("Evidence generation failed", error=str(result))
            continue
        evidence_cards.append(result)

    logger.info(
        "Evidence cards generated",
        total=len(papers),
        successful=len(evidence_cards),
    )

    return evidence_cards
