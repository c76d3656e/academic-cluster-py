"""
搜索节点 - 从多个学术数据源搜索论文

使用 LLM 生成优化的搜索 query（参考 Rust 版 parse_topic），
然后并行搜索多个数据源。
"""

import asyncio
import json
import traceback
import uuid

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from ...prompts import get_parse_topic_prompt
from ...tools.academic_search import search_all_sources
from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def _generate_search_queries(topic: str) -> list[str]:
    """使用 LLM 生成优化的搜索 query（对齐 Rust 版 parse_topic）"""
    from ...services.llm_client import create_llm
    llm = create_llm(temperature=0.3)

    prompt_template = get_parse_topic_prompt()
    if not prompt_template:
        # fallback: 直接使用原始 topic
        return [topic]

    prompt = prompt_template.format(topic=topic)

    messages = [
        SystemMessage(content="Return one compact JSON object only. No markdown. No reasoning. No explanation."),
        HumanMessage(content=prompt),
    ]

    try:
        response = await llm.ainvoke(messages)
        # LLM 响应 content 可能是 list（多模态格式）或 string
        content = response.content
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        content = content.strip()

        # 提取 JSON
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            content = content[start:end + 1]

        data = json.loads(content)
        queries = data.get("final_queries", [])

        if not queries:
            # fallback
            queries = [topic]

        logger.info("Search queries generated", queries=queries)
        return queries

    except Exception as e:
        logger.warning("Failed to generate search queries, using fallback", error=str(e))
        return [topic]


async def search_node(state: PipelineState) -> dict:
    """
    搜索学术论文

    1. 使用 LLM 将研究主题拆解为多个优化的英文搜索 query
    2. 并行搜索多个数据源
    3. 去重并保存
    """
    tracker = state.tracker if hasattr(state, 'tracker') else None
    if tracker:
        await tracker.begin_node("search", "search", index=0)

    try:
        logger.info("Starting paper search", query=state.query, project_id=state.project_id)

        config = state.config or {}
        limit_per_source = config.get("limit_per_source", 50)
        sources = config.get("sources", ["semantic_scholar", "arxiv", "openalex"])

        # 使用 LLM 生成优化的搜索 queries
        queries = await _generate_search_queries(state.query)

        # 并行搜索所有 queries × 所有数据源
        all_papers = []
        search_tasks = [
            search_all_sources(
                query=q,
                limit_per_source=limit_per_source,
                sources=sources,
            )
            for q in queries
        ]

        results = await asyncio.gather(*search_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Search query failed", error=str(result))
                continue
            all_papers.extend(result)

        # 去重（基于标题相似性）
        unique_papers = _deduplicate_papers(all_papers)

        # 保存到数据库并获取 ID
        db = get_database()
        paper_ids = []

        for paper in unique_papers:
            paper_id = paper.get("id", str(uuid.uuid4()))
            paper["id"] = paper_id

            try:
                actual_id = await db.save_paper(paper)
                paper_ids.append(actual_id)
            except Exception as e:
                logger.warning("Failed to save paper", paper_id=paper_id, error=str(e))

        total_searched = len(all_papers)

        logger.info(
            "Search completed",
            queries_count=len(queries),
            total_searched=total_searched,
            unique_papers=len(unique_papers),
            papers_saved=len(paper_ids),
        )

        result = {
            "paper_ids": paper_ids,
            "total_searched": total_searched,
            "status": "searched",
        }

        if tracker:
            await tracker.end_node("search", "succeeded", output_summary={
                "paper_count": len(paper_ids),
                "total_searched": total_searched,
                "sources": sources,
            })
        return result

    except Exception as e:
        if tracker:
            await tracker.end_node("search", "failed",
                                   error_message=str(e),
                                   error_traceback=traceback.format_exc())
        raise


def _deduplicate_papers(papers: list[dict]) -> list[dict]:
    """基于标题相似性去重"""
    seen_titles = set()
    unique_papers = []

    for paper in papers:
        title = paper.get("title", "").lower().strip()
        if not title:
            continue

        normalized_title = " ".join(title.split())
        if normalized_title not in seen_titles:
            seen_titles.add(normalized_title)
            unique_papers.append(paper)

    return unique_papers
