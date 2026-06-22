"""
搜索节点 - 从多个学术数据源搜索论文（对齐 Rust 版多轮搜索）

对齐 Rust 版 academic-cluster-rs 的 SearchSelectionSubgraph：
1. LLM 生成初始搜索 queries（最多 12 条）
2. 最多 3 轮搜索循环：
   a. 并行搜索所有数据源
   b. 去重（DOI 优先）
   c. 主题相关性过滤
   d. 覆盖度评估（evaluate_search）
   e. 如果不充分，生成补充 queries（refine_query，最多 8 条）
3. 最终验证：至少 20 篇相关论文
"""

import asyncio
import traceback
import uuid

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from ...prompts import (
    get_evaluate_search_prompt,
    get_parse_topic_prompt,
    get_refine_query_prompt,
)
from ...services.database import get_database
from ...services.observability import get_current_tracker
from ...tools.academic_search import search_all_sources
from ...tools.doi import is_valid_doi, normalize_doi
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()

# 默认常量（可通过 pipeline_config 覆盖）
_DEFAULT_INITIAL_QUERY_LIMIT = 12
_DEFAULT_REFINE_QUERY_LIMIT = 8
_DEFAULT_MAX_SEARCH_ROUNDS = 3
_DEFAULT_TARGET_RELEVANT = 50
_DEFAULT_MIN_RELEVANT = 20


def _normalize_title_for_dedup(title: str) -> str:
    """标准化标题用于去重"""
    import unicodedata

    title = title.strip().lower()
    return "".join(
        ch for ch in title if ch.isalnum() or unicodedata.category(ch).startswith("Lo")
    )


def _make_dedup_key(paper: dict) -> str:
    """为论文生成去重 key（对齐 Rust 版 dedup_candidates）"""
    # 1. 尝试 DOI
    doi = paper.get("doi")
    if not doi:
        ext_id = paper.get("external_id", "")
        if ext_id and (ext_id.startswith("10.") or "doi.org" in ext_id):
            doi = ext_id
    if doi:
        normalized = normalize_doi(doi)
        if normalized and is_valid_doi(normalized):
            return f"doi:{normalized}"

    # 2. 归一化标题
    title = paper.get("title", "")
    if title:
        norm_title = _normalize_title_for_dedup(title)
        if len(norm_title) >= 10:
            return f"title:{norm_title}"

    # 3. 兜底
    source = paper.get("source", "unknown")
    ext_id = paper.get("external_id", paper.get("id", ""))
    return f"source:{source}:{ext_id}"


def _deduplicate_papers(papers: list[dict]) -> list[dict]:
    """去重（对齐 Rust 版 dedup_candidates）"""
    seen_keys: set[str] = set()
    unique = []
    for paper in papers:
        key = _make_dedup_key(paper)
        if key not in seen_keys:
            seen_keys.add(key)
            unique.append(paper)
    return unique


def _is_topic_relevant(topic: str, queries: list[str], paper: dict) -> bool:
    """
    主题相关性过滤 - 快速关键词匹配（第一层）。

    检查论文标题或摘要是否包含主题词或搜索 query 中的关键词。
    """
    title = (paper.get("title") or "").lower()
    abstract = (paper.get("abstract") or "").lower()
    text = f"{title} {abstract}"

    if not text.strip():
        return True  # 无标题/摘要的论文保留（后续过滤）

    # 从 topic 和 queries 中提取关键词
    keywords = set()
    # topic 的关键词
    for word in topic.lower().split():
        if len(word) >= 3:
            keywords.add(word)
    # queries 中的关键词
    for q in queries:
        for word in q.lower().split():
            if len(word) >= 3:
                keywords.add(word)

    if not keywords:
        return True

    # 至少匹配 2 个关键词（或全部关键词如果少于 2 个）
    min_match = min(2, len(keywords))
    matched = sum(1 for kw in keywords if kw in text)
    return matched >= min_match


async def _llm_topic_relevance_filter(
    topic: str,
    papers: list[dict],
    batch_size: int = 30,
) -> list[dict]:
    """
    LLM 主题相关性过滤（对齐 Rust 版 is_topic_relevant_with_queries）。

    对关键词过滤后的论文进行批量 LLM 相关性判断。
    """
    from ...services.llm_client import ainvoke_with_callbacks, create_llm
    from ...tools.json_repair import try_parse_json

    if len(papers) <= 10:
        return papers  # 论文太少，跳过 LLM 过滤

    relevant_papers = []

    for batch_start in range(0, len(papers), batch_size):
        batch = papers[batch_start : batch_start + batch_size]

        # 构建论文摘要列表
        paper_lines = []
        for i, p in enumerate(batch, 1):
            title = p.get("title", "Untitled")
            abstract = (p.get("abstract") or "")[:200]
            paper_lines.append(f"{i}. {title}\n   {abstract}")
        papers_text = "\n".join(paper_lines)

        prompt = f"""判断以下论文是否与研究主题"{topic}"相关。

论文列表：
{papers_text}

返回 JSON：{{"relevant": [1, 3, 5]}} — 只包含相关论文的编号。
规则：
- 相关 = 论文直接研究该主题、使用相关方法、或在相关领域
- 不相关 = 论文虽然包含关键词但实际研究方向不同
- 如果不确定，倾向于保留"""

        try:
            llm = create_llm(temperature=0.0, max_tokens=1024)
            messages = [
                SystemMessage(
                    content="Return one compact JSON object only. No markdown."
                ),
                HumanMessage(content=prompt),
            ]
            response = await asyncio.wait_for(
                ainvoke_with_callbacks(llm, messages), timeout=30.0
            )
            content = response.content
            if isinstance(content, list):
                content = "".join(
                    block.get("text", "") if isinstance(block, dict) else str(block)
                    for block in content
                )

            data = try_parse_json(content)
            if data and "relevant" in data:
                relevant_indices = set(data["relevant"])
                for i, p in enumerate(batch, 1):
                    if i in relevant_indices:
                        relevant_papers.append(p)
            else:
                # 解析失败，保留整个 batch
                relevant_papers.extend(batch)

        except Exception as e:
            logger.warning(
                "LLM relevance filter failed for batch, keeping all", error=str(e)
            )
            relevant_papers.extend(batch)

    logger.info(
        "LLM topic relevance filter completed",
        input_count=len(papers),
        relevant_count=len(relevant_papers),
    )
    return relevant_papers


def _build_paper_summaries(papers: list[dict], max_count: int = 30) -> str:
    """构建论文摘要列表（用于覆盖度评估）"""
    lines = []
    for i, p in enumerate(papers[:max_count], 1):
        title = p.get("title", "Untitled")
        year = p.get("year", "?")
        source = p.get("source", "?")
        lines.append(f"{i}. [{source}] {title} ({year})")
    return "\n".join(lines)


async def _generate_search_queries(
    topic: str, max_queries: int = _DEFAULT_INITIAL_QUERY_LIMIT
) -> list[str]:
    """使用 LLM 生成优化的搜索 query（对齐 Rust 版 parse_topic）"""
    from ...services.llm_client import ainvoke_with_callbacks, create_llm

    llm = create_llm(temperature=0.3)

    prompt_template = get_parse_topic_prompt()
    if not prompt_template:
        return [topic]

    prompt = prompt_template.format(topic=topic)

    messages = [
        SystemMessage(
            content="Return one compact JSON object only. No markdown. No reasoning. No explanation."
        ),
        HumanMessage(content=prompt),
    ]

    try:
        response = await asyncio.wait_for(
            ainvoke_with_callbacks(llm, messages), timeout=60.0
        )
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
            content = content[start : end + 1]

        from ...tools.json_repair import try_parse_json

        data = try_parse_json(content)
        if data:
            queries = data.get("final_queries", [])
            if queries:
                return queries[:max_queries]

        return [topic]

    except Exception as e:
        logger.warning(
            "Failed to generate search queries, using fallback", error=str(e)
        )
        return [topic]


async def _evaluate_coverage(
    topic: str,
    queries: list[str],
    papers: list[dict],
) -> dict:
    """
    评估搜索结果的覆盖度（对齐 Rust 版 llm_source_coverage_judge）。

    返回: {"is_sufficient": bool, "identified_gaps": list[str]}
    """
    from ...services.llm_client import ainvoke_with_callbacks, create_llm

    prompt_template = get_evaluate_search_prompt()
    if not prompt_template:
        # fallback: 数量足够就认为充分
        return {
            "is_sufficient": len(papers) >= 50,
            "identified_gaps": [],
        }

    csv_summaries = _build_paper_summaries(papers, max_count=30)
    prompt = prompt_template.format(
        topic=topic,
        queries=", ".join(queries),
        csv_summaries=csv_summaries,
    )

    messages = [
        SystemMessage(content="Return one compact JSON object only. No markdown."),
        HumanMessage(content=prompt),
    ]

    try:
        llm = create_llm(temperature=0.0, max_tokens=1024)
        response = await asyncio.wait_for(
            ainvoke_with_callbacks(llm, messages), timeout=30.0
        )
        content = response.content
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )

        from ...tools.json_repair import try_parse_json

        data = try_parse_json(content)
        if data:
            return {
                "is_sufficient": data.get("is_sufficient", False),
                "identified_gaps": data.get("identified_gaps", []),
            }

    except Exception as e:
        logger.warning("Coverage evaluation failed, using fallback", error=str(e))

    # fallback
    return {
        "is_sufficient": len(papers) >= 50,  # fallback 默认值
        "identified_gaps": [],
    }


async def _refine_queries(
    topic: str,
    gaps: list[str],
    previous_queries: list[str],
    max_queries: int = _DEFAULT_REFINE_QUERY_LIMIT,
) -> list[str]:
    """
    基于缺口生成补充搜索 queries（对齐 Rust 版 llm_source_query_refine）。

    最多返回 REFINE_QUERY_LIMIT 条新 queries。
    """
    from ...services.llm_client import ainvoke_with_callbacks, create_llm

    prompt_template = get_refine_query_prompt()
    if not prompt_template:
        return []

    prompt = prompt_template.format(
        topic=topic,
        gaps="\n".join(f"- {g}" for g in gaps),
        previous_queries=", ".join(previous_queries),
    )

    messages = [
        SystemMessage(content="Return one compact JSON object only. No markdown."),
        HumanMessage(content=prompt),
    ]

    try:
        llm = create_llm(temperature=0.3, max_tokens=1024)
        response = await asyncio.wait_for(
            ainvoke_with_callbacks(llm, messages), timeout=30.0
        )
        content = response.content
        if isinstance(content, list):
            content = "".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in content
            )

        from ...tools.json_repair import try_parse_json

        data = try_parse_json(content)
        if data:
            new_queries = data.get("new_queries", [])
            if new_queries:
                return new_queries[:max_queries]

    except Exception as e:
        logger.warning("Query refinement failed", error=str(e))

    return []


async def search_node(state: PipelineState) -> dict:
    """
    搜索学术论文（对齐 Rust 版多轮搜索）

    1. LLM 生成初始搜索 queries
    2. 最多 3 轮搜索循环（每轮搜索 → 去重 → 相关性过滤 → 覆盖度评估 → 补充 queries）
    3. 最终验证：至少 20 篇相关论文
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("search", "search", index=0)

    try:
        logger.info(
            "Starting paper search", query=state.query, project_id=state.project_id
        )

        config = state.config or {}
        limit_per_source = config.get("limit_per_source", 200)
        sources = config.get(
            "sources", ["semantic_scholar", "openalex", "crossref", "arxiv", "pubmed"]
        )
        per_source_limits = {
            s: int(config.get(f"search.source_limit.{s}", limit_per_source))
            for s in sources
        }

        # 从 config 读取可调参数
        max_rounds = config.get("search.max_rounds", _DEFAULT_MAX_SEARCH_ROUNDS)
        initial_query_limit = config.get(
            "search.initial_query_limit", _DEFAULT_INITIAL_QUERY_LIMIT
        )
        refine_query_limit = config.get(
            "search.refine_query_limit", _DEFAULT_REFINE_QUERY_LIMIT
        )
        target_relevant = config.get("search.target_relevant", _DEFAULT_TARGET_RELEVANT)
        min_relevant = config.get("search.min_relevant", _DEFAULT_MIN_RELEVANT)

        # Phase 1: 初始 query 生成
        logger.info("Generating initial search queries...", query=state.query)
        queries = await _generate_search_queries(
            state.query, max_queries=initial_query_limit
        )
        all_queries = list(queries)  # 记录所有已搜索的 queries

        await send_progress(
            state.project_id,
            "search",
            f"生成 {len(queries)} 条搜索词，开始多轮搜索...",
            detail={"queries": queries, "sources": sources, "max_rounds": max_rounds},
        )

        # Phase 2: 多轮搜索循环
        all_papers: list[dict] = []
        source_counts: dict[str, int] = dict.fromkeys(sources, 0)

        for round_num in range(1, max_rounds + 1):
            logger.info(f"Search round {round_num}/{max_rounds}", queries=queries)

            await send_progress(
                state.project_id,
                "search",
                f"第 {round_num} 轮搜索：{len(queries)} 条搜索词 × {len(sources)} 个数据源...",
                detail={"round": round_num, "queries": queries},
            )

            # 并行搜索（用 create_task 包装，支持超时后检查 done/cancel）
            search_tasks = [
                asyncio.create_task(
                    search_all_sources(
                        query=q,
                        limit_per_source=limit_per_source,
                        sources=sources,
                        per_source_limits=per_source_limits,
                    )
                )
                for q in queries
            ]

            try:
                results = await asyncio.wait_for(
                    asyncio.gather(*search_tasks, return_exceptions=True),
                    timeout=120.0,
                )
            except TimeoutError:
                logger.error(f"Search round {round_num} timed out after 120s")
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

            # 收集本轮结果
            round_papers = []
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("Search query failed", error=str(result))
                    continue
                if isinstance(result, list):
                    round_papers.extend(result)
                    for paper in result:
                        src = paper.get("source", "unknown")
                        source_counts[src] = source_counts.get(src, 0) + 1

            # 合并并去重
            all_papers.extend(round_papers)
            all_papers = _deduplicate_papers(all_papers)

            # 主题相关性过滤
            relevant_papers = [
                p for p in all_papers if _is_topic_relevant(state.query, all_queries, p)
            ]

            logger.info(
                f"Round {round_num} completed",
                round_papers=len(round_papers),
                total_unique=len(all_papers),
                relevant=len(relevant_papers),
            )

            await send_progress(
                state.project_id,
                "search",
                f"第 {round_num} 轮完成：本轮 {len(round_papers)} 篇，累计去重 {len(all_papers)} 篇，相关 {len(relevant_papers)} 篇",
                detail={
                    "round": round_num,
                    "round_papers": len(round_papers),
                    "total_unique": len(all_papers),
                    "relevant": len(relevant_papers),
                },
            )

            # 覆盖度评估
            if len(relevant_papers) >= target_relevant:
                # 数量充足，评估覆盖度
                assessment = await _evaluate_coverage(
                    state.query, all_queries, relevant_papers
                )
                if assessment.get("is_sufficient", False):
                    logger.info(
                        "Coverage sufficient, stopping search",
                        relevant_count=len(relevant_papers),
                        round=round_num,
                    )
                    break
                gaps = assessment.get("identified_gaps", [])
            else:
                # 数量不足，继续搜索
                gaps = [
                    f"Only {len(relevant_papers)} relevant papers found, need at least {target_relevant}"
                ]

            # 最后一轮不再补充
            if round_num >= max_rounds:
                logger.info("Max search rounds reached, stopping")
                break

            # 生成补充 queries
            new_queries = await _refine_queries(
                state.query, gaps, all_queries, max_queries=refine_query_limit
            )
            if not new_queries:
                logger.info("No new queries generated, stopping search")
                break

            queries = new_queries
            all_queries.extend(new_queries)

            await send_progress(
                state.project_id,
                "search",
                f"补充 {len(new_queries)} 条搜索词，继续第 {round_num + 1} 轮...",
                detail={"new_queries": new_queries, "gaps": gaps},
            )

        # Phase 3: 最终验证
        # 第一层：关键词过滤
        keyword_relevant = [
            p for p in all_papers if _is_topic_relevant(state.query, all_queries, p)
        ]

        # 第二层：LLM 主题相关性过滤（对齐 Rust 版 is_topic_relevant_with_queries）
        # 仅当关键词过滤结果过多时启用，避免 LLM 超时浪费时间
        llm_filter_threshold = state.config.get("search.llm_filter_threshold", 5000)
        if len(keyword_relevant) > llm_filter_threshold:
            try:
                final_papers = await _llm_topic_relevance_filter(
                    state.query, keyword_relevant
                )
            except Exception as e:
                logger.warning(
                    "LLM relevance filter failed, using keyword results", error=str(e)
                )
                final_papers = keyword_relevant
        else:
            final_papers = keyword_relevant

        if not final_papers:
            logger.warning("No relevant papers found after all rounds")
            final_papers = all_papers  # 回退使用全部

        if len(final_papers) < min_relevant:
            logger.warning(
                "Insufficient relevant papers",
                relevant=len(final_papers),
                minimum=min_relevant,
            )

        # 保存到数据库
        db = get_database()
        paper_ids = []

        for paper in final_papers:
            paper_id = paper.get("id", str(uuid.uuid4()))
            paper["id"] = paper_id
            try:
                actual_id = await db.save_paper(paper)
                paper_ids.append(actual_id)
            except Exception as e:
                logger.warning("Failed to save paper", paper_id=paper_id, error=str(e))

        # 构建源统计摘要
        source_summary = ", ".join(
            f"{k}: {v}" for k, v in source_counts.items() if v > 0
        )

        await send_progress(
            state.project_id,
            "search",
            f"搜索完成：{len(paper_ids)} 篇相关论文（共搜索 {len(all_papers)} 篇去重后）[{source_summary}]",
            detail={
                "total_searched": len(all_papers),
                "relevant": len(final_papers),
                "saved": len(paper_ids),
                "source_counts": source_counts,
                "total_queries": len(all_queries),
                "sources": sources,
            },
        )

        logger.info(
            "Search completed",
            total_queries=len(all_queries),
            total_unique=len(all_papers),
            relevant=len(final_papers),
            papers_saved=len(paper_ids),
        )

        # 可用文献过少则提前报错，避免后续全流程空跑
        if len(paper_ids) < 200:
            error_msg = f"可用文献过少：仅搜索到 {len(paper_ids)} 篇论文（需至少 200 篇），请调整搜索词或数据源"
            logger.error(error_msg, project_id=state.project_id, query=state.query)
            await send_progress(state.project_id, "search", error_msg)
            if tracker:
                await tracker.end_node("search", "failed", error_message=error_msg)
            raise ValueError(error_msg)

        result = {
            "paper_ids": paper_ids,
            "total_searched": len(all_papers),
            "status": "searched",
        }

        if tracker:
            await tracker.end_node(
                "search",
                "succeeded",
                output_summary={
                    "paper_count": len(paper_ids),
                    "total_searched": len(all_papers),
                    "sources": sources,
                },
            )
        return result

    except Exception as e:
        error_msg = f"Search node failed: {type(e).__name__}: {e!s}"
        logger.error(
            "Search node failed",
            query=state.query,
            project_id=state.project_id,
            error=str(e),
            error_type=type(e).__name__,
            traceback=traceback.format_exc(),
        )

        if tracker:
            await tracker.end_node(
                "search",
                "failed",
                error_message=str(e),
                error_traceback=traceback.format_exc(),
            )

        await send_progress(
            state.project_id,
            "search",
            f"搜索出错: {e!s}，将用空结果继续",
            detail={"error": str(e), "error_type": type(e).__name__},
        )

        return {
            "paper_ids": [],
            "total_searched": 0,
            "status": "searched",
            "errors": [error_msg],
        }
