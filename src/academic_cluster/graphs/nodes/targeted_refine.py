"""
针对性精炼节点 - 根据差距分析补充搜索

使用 LLM 基于差距分析结果生成有针对性的搜索 query（对齐 Rust 版 cluster_targeted_refine）。
"""

import asyncio
import json
import traceback
import uuid
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from ...prompts import get_cluster_targeted_refine_prompt
from ...services.database import get_database
from ...services.observability import get_current_tracker
from ...tools.academic_search import search_all_sources
from ..state import PipelineState

logger = structlog.get_logger()


async def _generate_targeted_queries(
    topic: str,
    gaps: list[str],
    weak_clusters: list[dict[str, Any]],
    previous_queries: list[str],
) -> list[str]:
    """使用 LLM 生成针对性补充 query（对齐 Rust 版 cluster_targeted_refine）"""
    from ...services.llm_client import ainvoke_with_callbacks, create_llm

    llm = create_llm(temperature=0.3, task="writing")

    prompt_template = get_cluster_targeted_refine_prompt()
    if not prompt_template:
        # fallback
        return [f"{topic} methods", f"{topic} applications"]

    prompt = prompt_template.format(
        topic=topic,
        gaps="\n".join(f"- {g}" for g in gaps) if gaps else "None identified",
        weak_clusters=json.dumps(weak_clusters, ensure_ascii=False, indent=2)
        if weak_clusters
        else "None",
        previous_queries="\n".join(f"- {q}" for q in previous_queries)
        if previous_queries
        else "None",
    )

    messages = [
        SystemMessage(
            content="Return one compact JSON object only. No markdown. No reasoning. No explanation."
        ),
        HumanMessage(content=prompt),
    ]

    try:
        response = await ainvoke_with_callbacks(llm, messages)
        # LLM 响应 content 可能是 list（多模态格式）或 string
        content = response.content
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )
        content = content.strip()

        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end > start:
            content = content[start : end + 1]

        data = json.loads(content)
        result_queries: list[str] = data.get("new_queries", [])

        if not result_queries:
            result_queries = [f"{topic} methods", f"{topic} applications"]

        logger.info("Targeted queries generated", queries=result_queries)
        return result_queries

    except Exception as e:
        logger.warning(
            "Failed to generate targeted queries, using fallback", error=str(e)
        )
        return [f"{topic} methods", f"{topic} applications"]


async def targeted_refine_node(state: PipelineState) -> dict[str, Any]:
    """
    针对性精炼

    根据差距分析结果，使用 LLM 生成有针对性的补充搜索 query，
    然后搜索新论文并合并到现有论文列表。
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("targeted_refine", "llm", index=10)

    logger.info(
        "Starting targeted refinement",
        attempt=state.refinement_attempt + 1,
        max_attempts=state.max_refinement_attempts,
    )

    config = state.config or {}
    limit_per_source = config.get("targeted_search_limit", 20)

    db = get_database()

    try:
        # 从 gap_analysis 结果中提取信息
        gaps: list[str] = []
        weak_clusters: list[dict[str, Any]] = []
        previous_queries: list[str] = []

        if hasattr(state, "gap_analysis_result") and state.gap_analysis_result:
            gaps = state.gap_analysis_result.get("gaps", [])
            weak_clusters = state.gap_analysis_result.get("weak_clusters", [])

        # 收集已搜索过的 queries（从 config 或历史中获取）
        if hasattr(state, "searched_queries"):
            previous_queries = state.searched_queries or []

        # 使用 LLM 生成针对性 queries
        targeted_queries = await _generate_targeted_queries(
            topic=state.query,
            gaps=gaps,
            weak_clusters=weak_clusters,
            previous_queries=previous_queries,
        )

        # 并行搜索新论文
        search_tasks = [
            search_all_sources(
                query=q,
                limit_per_source=limit_per_source,
                sources=["semantic_scholar", "arxiv"],
            )
            for q in targeted_queries
        ]

        results = await asyncio.gather(*search_tasks, return_exceptions=True)
        new_papers: list[dict[str, Any]] = []
        for result in results:
            if isinstance(result, BaseException):
                logger.warning("Targeted search failed", error=str(result))
                continue
            new_papers.extend(result)

        # 去重（排除已有论文）
        existing_paper_ids = set(state.paper_ids)
        unique_new_papers = []

        for paper in new_papers:
            paper_id = paper.get("id")
            if paper_id and paper_id not in existing_paper_ids:
                unique_new_papers.append(paper)
                existing_paper_ids.add(paper_id)

        # 保存新论文
        new_paper_ids = []
        for paper in unique_new_papers[:50]:
            try:
                pid = paper.get("id", str(uuid.uuid4()))
                paper["id"] = pid
                await db.save_paper(paper)
                new_paper_ids.append(pid)
            except Exception as e:
                logger.warning("Failed to save targeted paper", error=str(e))

        logger.info(
            "Targeted refinement completed",
            targeted_queries=len(targeted_queries),
            new_papers=len(new_paper_ids),
            attempt=state.refinement_attempt + 1,
        )

        final_result: dict[str, Any] = {
            "paper_ids": new_paper_ids,
            "refinement_attempt": state.refinement_attempt + 1,
            "needs_targeted_refinement": False,
            "status": "refined",
        }
        if tracker:
            await tracker.end_node(
                "targeted_refine",
                "succeeded",
                output_summary={
                    "new_papers": len(new_paper_ids),
                    "queries": len(targeted_queries),
                },
            )
        return final_result

    except Exception as e:
        if tracker:
            await tracker.end_node(
                "targeted_refine",
                "failed",
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )
        logger.error("Targeted refinement failed", error=str(e))
        return {
            "paper_ids": [],
            "refinement_attempt": state.refinement_attempt + 1,
            "needs_targeted_refinement": False,
            "status": "refined",
            "errors": [f"Targeted refinement failed: {e!s}"],
        }
