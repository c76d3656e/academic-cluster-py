"""
Topic 相关性过滤节点

两种模式：
- 聚类前：过滤 paper_ids，移除弱相关论文后再进入聚类
- 聚类后：过滤 core/auxiliary，不足时从辅助文献补足

并发 LLM CoT 逐篇评估（0-1 分），单篇失败不影响其他论文，全部失败则降级保留原始列表。
"""

import asyncio
import json
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from ...prompts import get_topic_relevance_filter_prompt
from ...services.database import get_database
from ...services.llm_client import ainvoke_with_callbacks, create_llm
from ...services.observability import get_current_tracker
from ...services.provider_pool import get_llm_available_slots
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()

DEFAULT_TOPIC_RELEVANCE_THRESHOLD = 0.4
DEFAULT_TOPIC_RELEVANCE_TIMEOUT_S = 300
DEFAULT_TOPIC_RELEVANCE_CONCURRENCY = -1


def _parse_json_object(content: Any) -> dict[str, Any] | list[Any]:
    """Parse LLM JSON response, handling code blocks and partial JSON."""
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    text = str(content or "").strip()
    if not text:
        raise ValueError("empty LLM response")
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start_obj = text.find("{")
        start_arr = text.find("[")
        if start_obj < 0 and start_arr < 0:
            raise
        if start_obj < 0:
            start = start_arr
            end = text.rfind("]")
        elif start_arr < 0:
            start = start_obj
            end = text.rfind("}")
        elif start_arr < start_obj:
            start = start_arr
            end = text.rfind("]")
        else:
            start = start_obj
            end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, (dict, list)):
        raise ValueError(
            f"LLM response is not a JSON object or array, got {type(value).__name__}"
        )
    return value


async def _evaluate_single_paper(
    paper: dict[str, Any],
    topic: str,
    timeout_s: int,
) -> tuple[str, float]:
    """Evaluate a single paper for topic relevance via LLM CoT.

    Returns (paper_id, relevance_score).
    Raises on LLM transport errors; returns default score on parse failures.
    """
    prompt_template = get_topic_relevance_filter_prompt()
    paper_data = [
        {
            "paper_id": str(paper.get("id", "")),
            "title": paper.get("title", ""),
            "abstract": (paper.get("abstract") or "")[:600],
        }
    ]

    prompt = prompt_template.format(
        topic=topic,
        papers=json.dumps(paper_data, ensure_ascii=False, indent=2),
    )

    llm = create_llm(temperature=0.1)
    response = await ainvoke_with_callbacks(
        llm,
        [
            SystemMessage(
                content="你是学术文献相关性评估专家。返回严格 JSON，不要其他文本。"
            ),
            HumanMessage(content=prompt),
        ],
        timeout=timeout_s,
    )

    paper_id = str(paper.get("id", ""))

    try:
        raw = _parse_json_object(response.content)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(
            "Failed to parse LLM response, using default score",
            paper_id=paper_id,
            error=str(e)[:200],
            content_preview=str(response.content)[:200],
        )
        return paper_id, 0.5

    assessments = raw if isinstance(raw, list) else raw.get("assessments", [])

    score = 0.5  # 默认中性分数
    for item in assessments:
        pid = str(item.get("paper_id", ""))
        if pid == paper_id:
            s = item.get("relevance_score")
            if isinstance(s, (int, float)):
                score = max(0.0, min(1.0, float(s)))
            break

    return paper_id, score


async def topic_relevance_filter_node(state: PipelineState) -> dict[str, Any]:
    """
    Topic 相关性过滤

    两种模式：
    - 聚类前（core/aux 为空，paper_ids 存在）：过滤所有论文，返回过滤后的 paper_ids
    - 聚类后（core/aux 存在）：过滤 core/aux，不足时从 auxiliary 补足

    并发处理，单篇失败不影响其他论文，全部失败时降级保留原始列表。
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("topic_relevance_filter", "llm", index=7)

    config = state.config or {}
    if not config.get("topic_relevance_enabled", True):
        logger.info("Topic relevance filter disabled, skipping")
        if tracker:
            await tracker.end_node(
                "topic_relevance_filter",
                "succeeded",
                output_summary={"skipped": True},
            )
        return {}

    threshold = float(
        config.get("topic_relevance_threshold", DEFAULT_TOPIC_RELEVANCE_THRESHOLD)
    )
    timeout_s = int(
        config.get("topic_relevance_timeout_s", DEFAULT_TOPIC_RELEVANCE_TIMEOUT_S)
    )

    core_ids = list(state.core_paper_ids or [])
    aux_ids = list(state.auxiliary_paper_ids or [])

    # 判断模式：core/aux 为空时从 paper_ids 取所有论文（聚类前过滤）
    pre_clustering = not core_ids and not aux_ids
    if pre_clustering:
        all_paper_ids = list(state.paper_ids or [])
    else:
        all_paper_ids = core_ids + aux_ids

    if not all_paper_ids:
        logger.info("No papers to evaluate for topic relevance")
        if tracker:
            await tracker.end_node(
                "topic_relevance_filter",
                "succeeded",
                output_summary={"no_papers": True},
            )
        return {}

    # 幂等性：已评估过的论文跳过，只评估新增的
    existing_scores = dict(state.topic_relevance_scores or {})
    new_paper_ids = [pid for pid in all_paper_ids if pid not in existing_scores]

    logger.info(
        "Starting topic relevance filter",
        mode="pre-clustering" if pre_clustering else "post-clustering",
        core_count=len(core_ids),
        auxiliary_count=len(aux_ids),
        total_papers=len(all_paper_ids),
        already_scored=len(existing_scores),
        new_to_evaluate=len(new_paper_ids),
        threshold=threshold,
    )

    if not new_paper_ids:
        logger.info("All papers already scored, skipping LLM evaluation")
    else:
        await send_progress(
            state.project_id,
            "topic_relevance_filter",
            f"正在评估 {len(new_paper_ids)} 篇新增论文的 Topic 相关性（已有 {len(existing_scores)} 篇分数）...",
        )

    db = get_database()
    papers = await db.get_papers_by_ids(new_paper_ids)

    # 并发度：参考 evidence_cards，使用 provider slots
    requested_concurrency = int(
        config.get("topic_relevance_concurrency", DEFAULT_TOPIC_RELEVANCE_CONCURRENCY)
    )
    provider_slots = get_llm_available_slots(default=10)
    concurrency = (
        provider_slots
        if requested_concurrency <= 0
        else min(requested_concurrency, provider_slots)
    )
    concurrency = max(1, concurrency)
    logger.info(
        "Topic relevance concurrency resolved",
        requested=requested_concurrency,
        provider_slots=provider_slots,
        effective=concurrency,
    )

    new_scores: dict[str, float] = {}
    failed_count = 0

    if new_paper_ids:
        semaphore = asyncio.Semaphore(concurrency)
        completed_count = 0
        total_new = len(papers)
        completed_lock = asyncio.Lock()

        async def _bounded_evaluate(
            idx: int, paper: dict[str, Any]
        ) -> tuple[str, float | None, Exception | None]:
            nonlocal completed_count
            async with semaphore:
                try:
                    result = await asyncio.wait_for(
                        _evaluate_single_paper(paper, state.query, timeout_s),
                        timeout=timeout_s + 30,
                    )
                    return result[0], result[1], None
                except Exception as e:
                    paper_id = str(paper.get("id", ""))
                    err_type = type(e).__name__
                    logger.warning(
                        "Paper evaluation failed",
                        paper_id=paper_id,
                        error_type=err_type,
                        error=str(e)[:200],
                    )
                    return paper_id, None, e
                finally:
                    async with completed_lock:
                        completed_count += 1
                        if completed_count % 10 == 0 or completed_count == total_new:
                            await send_progress(
                                state.project_id,
                                "topic_relevance_filter",
                                f"相关性评估中 {completed_count}/{total_new}...",
                                progress=completed_count / total_new,
                            )

        tasks = [_bounded_evaluate(i, paper) for i, paper in enumerate(papers)]

        for future in asyncio.as_completed(tasks):
            paper_id, score, error = await future
            if error:
                failed_count += 1
                logger.debug(
                    "Paper relevance evaluation failed",
                    paper_id=paper_id,
                    error=str(error),
                )
            elif score is not None:
                new_scores[paper_id] = score

    # 合并已有分数和新评估分数
    scores = {**existing_scores, **new_scores}

    # 全部新论文评估失败且无历史分数时降级
    if not scores:
        logger.warning("All LLM evaluations failed, preserving original paper lists")
        await send_progress(
            state.project_id,
            "topic_relevance_filter",
            "相关性评估失败，保留原始列表",
        )
        if tracker:
            await tracker.end_node(
                "topic_relevance_filter",
                "succeeded",
                output_summary={"degraded": True},
            )
        return {
            "topic_relevance_scores": {},
            "topic_filtered_count": 0,
            "status": "relevance_filter_degraded",
        }

    if pre_clustering:
        # 聚类前模式：过滤所有论文，返回 paper_ids
        filtered_ids = [
            pid for pid in all_paper_ids if scores.get(pid, 0.0) >= threshold
        ]
        filtered_count = len(all_paper_ids) - len(filtered_ids)

        logger.info(
            "Topic relevance filter completed (pre-clustering)",
            original=len(all_paper_ids),
            filtered=len(filtered_ids),
            filtered_count=filtered_count,
            threshold=threshold,
            already_scored=len(existing_scores),
            new_evaluated=len(new_scores),
            failed_count=failed_count,
        )

        await send_progress(
            state.project_id,
            "topic_relevance_filter",
            f"相关性过滤完成，移除 {filtered_count} 篇弱相关论文",
        )

        result: dict[str, Any] = {
            "paper_ids": filtered_ids,
            "topic_relevance_scores": scores,
            "topic_filtered_count": filtered_count,
            "status": "relevance_filtered",
        }
    else:
        # 聚类后模式：过滤 core/aux，补足核心文献
        filtered_core = [pid for pid in core_ids if scores.get(pid, 0.0) >= threshold]
        filtered_aux = [pid for pid in aux_ids if scores.get(pid, 0.0) >= threshold]

        target = int(config.get("core_reference_count", 160))
        if len(filtered_core) < target:
            already_in_core = set(filtered_core)
            available = [pid for pid in filtered_aux if pid not in already_in_core]
            need = target - len(filtered_core)
            filtered_core.extend(available[:need])
            promoted = set(available[:need])
            filtered_aux = [pid for pid in filtered_aux if pid not in promoted]

        original_count = len(core_ids) + len(aux_ids)
        filtered_count = original_count - len(filtered_core) - len(filtered_aux)

        logger.info(
            "Topic relevance filter completed (post-clustering)",
            original_core=len(core_ids),
            filtered_core=len(filtered_core),
            original_aux=len(aux_ids),
            filtered_aux=len(filtered_aux),
            filtered_count=filtered_count,
            threshold=threshold,
            already_scored=len(existing_scores),
            new_evaluated=len(new_scores),
            failed_count=failed_count,
        )

        await send_progress(
            state.project_id,
            "topic_relevance_filter",
            f"相关性过滤完成，移除 {filtered_count} 篇弱相关论文",
        )

        result = {
            "core_paper_ids": filtered_core,
            "auxiliary_paper_ids": filtered_aux,
            "topic_relevance_scores": scores,
            "topic_filtered_count": filtered_count,
            "status": "relevance_filtered",
        }

    if tracker:
        summary: dict[str, Any] = {"filtered_count": filtered_count}
        if not pre_clustering:
            summary["core_after"] = len(filtered_core)
            summary["aux_after"] = len(filtered_aux)
        else:
            summary["papers_after"] = len(filtered_ids)
        await tracker.end_node(
            "topic_relevance_filter",
            "succeeded",
            output_summary=summary,
        )

    return result
