"""
查询规划 Agent

负责分析研究主题，生成优化的搜索查询。
这是一个 Agent，因为它需要：
- 理解研究主题的语义
- 决定使用哪些搜索源
- 生成多个相关的搜索查询
- 评估搜索结果质量
"""

from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

logger = structlog.get_logger()


# =============================================================================
# Tools - 被 Agent 调用的确定性函数
# =============================================================================


@tool
def refine_search_query(query: str) -> str:
    """优化搜索查询，使其更适合学术搜索"""
    # 确定性逻辑：清理和规范化查询
    cleaned = query.strip()
    # 移除多余的空格
    cleaned = " ".join(cleaned.split())
    return cleaned


@tool
def generate_search_queries(topic: str, num_queries: int = 3) -> list[str]:
    """
    基于主题生成多个搜索查询

    使用不同的角度和关键词组合来扩大搜索范围
    """
    # 这个工具本身不调用 LLM，只是格式化
    # 实际的查询生成由 Agent 的 LLM 完成
    queries = []

    # 基础查询
    queries.append(topic)

    # 添加变体（实际应该由 LLM 生成）
    # 这里只是占位示例
    if "machine learning" in topic.lower():
        queries.append(topic.replace("machine learning", "ML"))
        queries.append(topic.replace("machine learning", "deep learning"))

    return queries[:num_queries]


@tool
def select_search_sources(topic: str) -> list[str]:
    """
    选择最适合的学术搜索源

    根据主题特点选择：
    - semantic_scholar: 通用学术搜索
    - pubmed: 生物医学相关
    - arxiv: 计算机科学、物理学
    - openalex: 开放获取
    """
    # 默认使用所有源
    sources = ["semantic_scholar", "pubmed", "arxiv", "openalex"]

    # 根据主题关键词调整优先级
    topic_lower = topic.lower()

    bio_keywords = ["biology", "medical", "health", "disease", "drug", "genomic"]
    cs_keywords = ["computer", "algorithm", "neural", "deep learning", "AI", "NLP"]

    if any(kw in topic_lower for kw in bio_keywords):
        # 生物医学主题，优先 PubMed
        sources = ["pubmed", "semantic_scholar", "openalex"]
    elif any(kw in topic_lower for kw in cs_keywords):
        # 计算机科学主题，优先 arXiv
        sources = ["arxiv", "semantic_scholar", "openalex"]

    return sources


@tool
def evaluate_search_results(papers: list[dict[str, Any]]) -> dict[str, Any]:
    """
    评估搜索结果质量

    返回质量指标：
    - total_count: 总论文数
    - avg_citations: 平均引用数
    - year_distribution: 年份分布
    - quality_score: 质量分数 (0-1)
    """
    if not papers:
        return {
            "total_count": 0,
            "avg_citations": 0,
            "quality_score": 0.0,
        }

    total = len(papers)
    citations = [p.get("citation_count", 0) for p in papers]
    avg_citations = sum(citations) / total if total > 0 else 0

    # 简单的质量评分
    quality_score = min(1.0, total / 100)  # 论文数量贡献
    quality_score += min(1.0, avg_citations / 50) * 0.3  # 引用贡献
    quality_score = min(1.0, quality_score)

    return {
        "total_count": total,
        "avg_citations": avg_citations,
        "quality_score": quality_score,
    }


# =============================================================================
# Agent 创建
# =============================================================================


def create_query_planning_agent(
    model: str | None = None,
    temperature: float = 0.3,
) -> Any:
    """
    创建查询规划 Agent

    Args:
        model: LLM 模型名称，默认从配置读取
        temperature: 温度参数，查询规划需要较低的随机性

    Returns:
        绑定了工具的 LLM 实例
    """
    from ..services.llm_client import create_llm

    # 创建 LLM
    llm = create_llm(temperature=temperature, task="search")

    # 绑定工具
    agent = llm.bind_tools(
        [
            refine_search_query,
            generate_search_queries,
            select_search_sources,
            evaluate_search_results,
        ]
    )

    logger.info("Query planning agent created", model=model)

    return agent


# =============================================================================
# Agent 调用函数
# =============================================================================

QUERY_PLANNING_SYSTEM_PROMPT = """你是一个学术搜索查询规划专家。你的任务是：

1. 分析用户的研究主题
2. 生成多个优化的搜索查询
3. 选择最适合的学术搜索源
4. 评估搜索结果质量

请确保：
- 查询覆盖主题的不同方面
- 使用学术术语和同义词
- 考虑中英文表达
- 为每个搜索源优化查询格式

输出格式：
- queries: 优化后的查询列表
- sources: 推荐的搜索源及其优先级
- reasoning: 你的推理过程
"""


async def plan_queries(topic: str) -> dict[str, Any]:
    """
    执行查询规划

    Args:
        topic: 研究主题

    Returns:
        包含查询计划的字典
    """
    agent = create_query_planning_agent()

    messages = [
        SystemMessage(content=QUERY_PLANNING_SYSTEM_PROMPT),
        HumanMessage(content=f"请为以下研究主题规划搜索查询：\n\n{topic}"),
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

    # 解析响应
    # TODO: 解析 LLM 响应，提取查询和源
    result = {
        "queries": [topic],  # 默认使用原始主题
        "sources": ["semantic_scholar", "pubmed", "arxiv", "openalex"],
        "reasoning": raw_content,
    }

    logger.info(
        "Query planning completed",
        topic=topic,
        queries_count=len(result["queries"]),
    )

    return result
