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
from .progress import send_progress

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

        await send_progress(
            state.project_id, "search",
            f"正在搜索 {len(sources)} 个学术源...",
            detail={"sources": sources, "queries": queries},
        )

        # 并行搜索所有 queries × 所有数据源
        all_papers = []
        source_counts: dict[str, int] = {s: 0 for s in sources}
        search_tasks = [
            search_all_sources(
                query=q,
                limit_per_source=limit_per_source,
                sources=sources,
            )
            for q in queries
        ]

        # 总体超时保护：单个 query 搜索超过 120 秒则跳过
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*search_tasks, return_exceptions=True),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            logger.error(
                "Search timed out after 120s",
                query=state.query,
                queries=queries,
                sources=sources,
            )
            # 尝试从已完成的任务中收集结果
            results = []
            for task in search_tasks:
                if task.done() and not task.cancelled():
                    try:
                        results.append(task.result())
                    except Exception:
                        results.append([])
                else:
                    task.cancel()
                    results.append([])

        for result in results:
            if isinstance(result, Exception):
                logger.warning(
                    "Search query failed",
                    query=state.query,
                    error=str(result),
                    error_type=type(result).__name__,
                )
                continue
            if isinstance(result, list):
                all_papers.extend(result)
                # 统计每个源的结果数
                for paper in result:
                    src = paper.get("source", "unknown")
                    source_counts[src] = source_counts.get(src, 0) + 1

        # 去重（基于标题相似性）
        unique_papers = _deduplicate_papers(all_papers)

        # 构建详细的进度消息
        source_summary = ", ".join(
            f"{k}: {v}" for k, v in source_counts.items() if v > 0
        )
        progress_msg = f"搜索完成，共找到 {len(all_papers)} 篇论文（去重后 {len(unique_papers)} 篇）"
        if source_summary:
            progress_msg += f" [{source_summary}]"

        await send_progress(
            state.project_id, "search",
            progress_msg,
            detail={
                "total_searched": len(all_papers),
                "unique": len(unique_papers),
                "source_counts": source_counts,
                "sources": sources,
            },
        )

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
        error_msg = f"Search node failed: {type(e).__name__}: {str(e)}"
        logger.error(
            "Search node failed",
            query=state.query,
            project_id=state.project_id,
            error=str(e),
            error_type=type(e).__name__,
            traceback=traceback.format_exc(),
        )

        if tracker:
            await tracker.end_node("search", "failed",
                                   error_message=str(e),
                                   error_traceback=traceback.format_exc())

        # 搜索失败时记录错误但不中断 pipeline，用空结果继续
        await send_progress(
            state.project_id, "search",
            f"搜索出错: {str(e)}，将用空结果继续",
            detail={"error": str(e), "error_type": type(e).__name__},
        )

        return {
            "paper_ids": [],
            "total_searched": 0,
            "status": "searched",
            "errors": [error_msg],
        }


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
