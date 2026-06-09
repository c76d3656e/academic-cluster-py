"""
搜索节点 - 从多个学术数据源搜索论文
"""

import asyncio

import structlog

from ..state import PipelineState

logger = structlog.get_logger()


async def search_node(state: PipelineState) -> dict:
    """
    搜索学术论文

    使用 LLM Agent 进行查询规划，然后并行搜索多个数据源：
    - Semantic Scholar
    - PubMed
    - arXiv
    - OpenAlex
    - Crossref
    """
    logger.info("Starting paper search", query=state.query, project_id=state.project_id)

    # TODO: 实现查询规划 Agent
    # query_plan = await query_planning_agent.ainvoke({"query": state.query})

    # TODO: 并行搜索多个数据源
    # results = await asyncio.gather(
    #     search_semantic_scholar(query_plan),
    #     search_pubmed(query_plan),
    #     search_arxiv(query_plan),
    #     search_openalex(query_plan),
    # )

    # 暂时返回模拟结果
    paper_ids = []
    total_searched = 0

    logger.info(
        "Search completed",
        total_searched=total_searched,
        papers_found=len(paper_ids),
    )

    return {
        "paper_ids": paper_ids,
        "total_searched": total_searched,
        "status": "searched",
    }
