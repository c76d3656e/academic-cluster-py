"""
学术研究 Agent 工具 — 真正的工具实现

核心设计原则：
1. 工具是 Agent 的手和眼 — 执行真实工作
2. 大量数据（论文全文）不进 Agent context — 存 DB，context 里只放摘要/IDs
3. 每个搜索/分析动作有明确的输入/输出 schema

Agent context 预算：
- 每个 search_papers 返回 ~500 tokens（统计数据 + top 5）
- 评估/分析工具返回 ~500 tokens（结构化 JSON）
- Agent 的 messages 永远保持在 10K tokens 以内
"""

from __future__ import annotations

import asyncio
import functools
import json
import math
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, ParamSpec, TypeVar

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

logger = structlog.get_logger()

_FALLBACK_EVIDENCE_LIMITATION = (
    "LLM evidence card extraction did not return a usable card for this paper."
)

_P = ParamSpec("_P")
_R = TypeVar("_R")


def _validated_coverage_score(value: Any) -> float:
    """Return one finite coverage score in the documented 0..1 range."""

    if isinstance(value, bool):
        raise ValueError("coverage_score must be a number between 0 and 1")
    try:
        score = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError("coverage_score must be a number between 0 and 1") from error
    if not math.isfinite(score) or not 0.0 <= score <= 1.0:
        raise ValueError("coverage_score must be finite and between 0 and 1")
    return score


def _normalized_text_items(value: Any) -> list[str]:
    """Accept only bounded non-empty strings from structured LLM list fields."""

    if not isinstance(value, list):
        return []
    return [
        str(item).strip()[:500]
        for item in value[:50]
        if isinstance(item, str) and item.strip()
    ]


def _is_fallback_evidence_card(card: dict[str, Any]) -> bool:
    """Recognize transient placeholder cards, including legacy persisted rows."""

    if card.get("source_api") == "fallback_missing_card":
        return True
    try:
        confidence = float(card.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return (
        confidence <= 0.05
        and str(card.get("limitation") or "").strip() == _FALLBACK_EVIDENCE_LIMITATION
    )


def _bind_kg_relation_entity_ids(
    relations: list[dict[str, Any]],
    persisted_entity_ids: dict[str, str],
) -> tuple[list[dict[str, Any]], int]:
    """Bind relation endpoints to the IDs returned by normalized entity upserts."""

    from ..agents.kg_extraction import normalized_name

    bound: list[dict[str, Any]] = []
    unresolved = 0
    for relation in relations:
        source_id = persisted_entity_ids.get(
            normalized_name(str(relation.get("source") or ""))
        )
        target_id = persisted_entity_ids.get(
            normalized_name(str(relation.get("target") or ""))
        )
        if not source_id or not target_id:
            unresolved += 1
            continue
        bound.append(
            {
                **relation,
                "source_entity_id": source_id,
                "target_entity_id": target_id,
            }
        )
    return bound, unresolved


def _audit_summary(value: Any, limit: int = 1500) -> str:
    try:
        rendered = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        rendered = str(value)
    return rendered[:limit]


def _reported_tool_error(output: Any) -> RuntimeError | None:
    """Return an error for tools that report failure as a JSON payload."""

    payload = output
    if isinstance(output, str):
        try:
            payload = json.loads(output)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(payload, dict) or not payload.get("error"):
        return None
    return RuntimeError(str(payload["error"])[:1500])


async def _record_tool_audit(
    *,
    agent_name: str,
    tool_name: str,
    inputs: Any,
    output: Any,
    started: float,
    status: str,
    error: BaseException | None = None,
) -> None:
    from ..services.observability import get_current_execution, get_current_project

    execution_id = get_current_execution()
    project_id = get_current_project()
    if not execution_id or not project_id:
        return
    try:
        from ..services.database import get_database

        await asyncio.wait_for(
            get_database().record_agent_tool_call(
                execution_id=execution_id,
                project_id=project_id,
                agent_name=agent_name,
                tool_name=tool_name,
                input_summary=_audit_summary(inputs),
                output_summary=None if output is None else _audit_summary(output),
                duration_ms=max(0, int((time.monotonic() - started) * 1000)),
                status=status,
                error_message=None if error is None else str(error)[:1500],
            ),
            timeout=2.0,
        )
    except Exception as audit_error:
        logger.warning(
            "Failed to persist Agent tool audit",
            tool=tool_name,
            error=str(audit_error),
        )


def _audited_agent_tool(
    agent_name: str,
) -> Callable[
    [Callable[_P, Awaitable[_R]]],
    Callable[_P, Awaitable[_R]],
]:
    """Record one tool invocation without coupling tool success to audit storage."""

    def decorate(
        function: Callable[_P, Awaitable[_R]],
    ) -> Callable[_P, Awaitable[_R]]:
        @functools.wraps(function)
        async def wrapped(*args: _P.args, **kwargs: _P.kwargs) -> _R:
            started = time.monotonic()
            inputs = {"args": args, "kwargs": kwargs}
            try:
                output = await function(*args, **kwargs)
            except asyncio.CancelledError as error:
                await _record_tool_audit(
                    agent_name=agent_name,
                    tool_name=function.__name__,
                    inputs=inputs,
                    output=None,
                    started=started,
                    status="interrupted",
                    error=error,
                )
                raise
            except Exception as error:
                await _record_tool_audit(
                    agent_name=agent_name,
                    tool_name=function.__name__,
                    inputs=inputs,
                    output=None,
                    started=started,
                    status="failed",
                    error=error,
                )
                raise
            reported_error = _reported_tool_error(output)
            await _record_tool_audit(
                agent_name=agent_name,
                tool_name=function.__name__,
                inputs=inputs,
                output=output,
                started=started,
                status="failed" if reported_error is not None else "succeeded",
                error=reported_error,
            )
            return output

        return wrapped

    return decorate


# =============================================================================
# Research Team 工具 — 搜索，只返回摘要
# =============================================================================


@tool
@_audited_agent_tool("research")
async def search_papers(
    query: Annotated[str, "搜索查询字符串"],
    limit_per_source: Annotated[int, "每个数据源最大返回论文数"] = 100,
) -> str:
    """搜索学术论文。在多个学术数据源（Semantic Scholar, arXiv, PubMed, Crossref, OpenAlex）上并发搜索。
    论文自动存入数据库。返回搜索结果统计和 top-5 论文标题。
    只返回 ~500 tokens 的摘要，不是完整的论文 JSON。"""
    from ..tools.academic_search import search_all_sources

    sources = ["semantic_scholar", "arxiv", "pubmed", "crossref", "openalex"]

    results = await search_all_sources(
        query=query,
        limit_per_source=max(1, min(limit_per_source, 20)),
        sources=sources,
    )

    from ..services.observability import (
        get_current_execution,
        get_current_project,
    )

    project_id = get_current_project()
    execution_id = get_current_execution()
    if not project_id or not execution_id:
        raise RuntimeError("search_papers requires project and execution context")

    # Deduplicate, persist globally, then link the exact saved IDs to this project.
    seen_titles: set[str] = set()
    paper_ids: list[str] = []
    top_titles: list[str] = []

    from ..services.database import get_database

    db = get_database()
    for paper in results:
        title = str(paper.get("title") or "").strip()
        if not title or title.casefold() in seen_titles:
            continue
        seen_titles.add(title.casefold())
        actual_id = await db.save_paper(paper)
        paper_ids.append(actual_id)
        if len(top_titles) < 5:
            top_titles.append(f"{title[:100]} ({paper.get('year', '')})")
    newly_linked = await db.link_project_papers(
        project_id,
        paper_ids,
        execution_id=execution_id,
        source_query=query,
    )

    # 源代码级按年份统计
    years: dict[int, int] = {}
    for p in results[:200]:
        y = p.get("year")
        if y:
            try:
                yi = int(str(y)[:4])
                if 2010 <= yi <= 2030:
                    years[yi] = years.get(yi, 0) + 1
            except (ValueError, TypeError):
                pass

    summary = {
        "query": query,
        "total_found": len(results),
        "unique_saved": newly_linked,
        "paper_ids_count": len(paper_ids),
        "top_titles": top_titles,
        "year_range": f"{min(years.keys())}-{max(years.keys())}"
        if years
        else "unknown",
    }
    logger.info(
        "search_papers completed",
        query=query,
        matched=len(paper_ids),
        newly_linked=newly_linked,
    )
    return json.dumps(summary, ensure_ascii=False)


@tool
@_audited_agent_tool("research")
async def finalize_research(
    summary_json: Annotated[str, "搜索汇总 JSON——包含所有已执行的查询及其统计信息"],
    total_papers: Annotated[int, "找到的总论文数（去重后）"],
    queries_used: Annotated[str, "已使用的所有查询（逗号分隔）"],
) -> str:
    """完成研究阶段。将所有搜索结果提交给 Orchestrator 进行下一步分析。"""
    logger.info("Research finalized", total_papers=total_papers, queries=queries_used)
    return json.dumps(
        {
            "status": "research_complete",
            "total_papers": total_papers,
            "queries_used": queries_used,
        },
        ensure_ascii=False,
    )


# =============================================================================
# Analysis Team 工具 — 聚类 + 评估，这才是真正的覆盖度分析
# =============================================================================


@tool
@_audited_agent_tool("analysis")
async def cluster_and_evaluate_coverage(
    topic: Annotated[str, "研究主题"],
    target_papers: Annotated[int, "目标论文数"],
    embedding_model: Annotated[str, "本次分析使用的 Embedding 模型组"],
) -> str:
    """对已搜索到的论文进行聚类分析，评估搜索覆盖度。
    这是真正的覆盖度评估——不是靠 LLM 猜测，而是靠 Leiden 聚类：
    1. 加载所有已搜索到的论文
    2. 构建 KNN + KG 混合图
    3. Leiden 社区检测，识别研究子方向
    4. 分析每个社区的主题、覆盖了哪些子领域、还缺什么

    返回结构化的覆盖度报告 JSON。"""
    try:
        from ..services.database import get_database
        from ..services.observability import get_current_project

        db = get_database()
        project_id = get_current_project()
        if not project_id:
            raise RuntimeError("coverage analysis requires project context")

        papers = await db.get_project_papers(project_id, limit=500)
        if not papers:
            return json.dumps(
                {
                    "cluster_count": 0,
                    "total_papers": 0,
                    "covered_aspects": [],
                    "missing_aspects": [topic],
                    "suggested_new_queries": [topic],
                    "coverage_score": 0.0,
                },
                ensure_ascii=False,
            )

        paper_ids = [str(p.get("id", "")) for p in papers if p.get("id")]
        paper_ids = [pid for pid in paper_ids if pid]

        if len(paper_ids) < 3:
            return json.dumps(
                {
                    "cluster_count": 1,
                    "total_papers": len(paper_ids),
                    "covered_aspects": [topic],
                    "missing_aspects": [],
                    "suggested_new_queries": [],
                    "coverage_score": min(1.0, len(paper_ids) / max(1, target_papers)),
                },
                ensure_ascii=False,
            )

        # 1. KNN 图
        from ..services.vector_store import get_vector_store

        vector_store = get_vector_store()
        knn_edges = await vector_store.get_knn_graph(
            paper_ids=paper_ids,
            k=8,
            threshold=0.3,
            model_name=embedding_model,
        )

        # 2. 社区检测
        from ..tools.clustering import build_hybrid_graph, community_detection

        def build_clusters() -> list[dict[str, Any]]:
            """Keep NetworkX/Leiden CPU work off the shared ASGI event loop."""

            hybrid_graph = build_hybrid_graph(
                knn_edges=knn_edges,
                kg_relations=[],
                kg_entities=[],
                evidence_cards=[],
                core_paper_ids=paper_ids,
                weights={
                    "knn": 0.80,
                    "kg_relation": 0.10,
                    "shared_entity": 0.05,
                    "evidence": 0.0,
                    "quality": 0.05,
                },
            )
            return community_detection(
                graph=hybrid_graph,
                algorithm="leiden",
                resolution=1.0,
                seed=42,
            )

        clusters = await asyncio.to_thread(build_clusters)

        # 3. 分析每一个社区
        covered_aspects: list[str] = []
        for cluster in clusters:
            c_paper_ids = cluster.get("paper_ids", [])
            c_size = len(c_paper_ids)
            entities = []
            for pid in c_paper_ids[:30]:
                p = next((x for x in papers if str(x.get("id")) == pid), None)
                if p and p.get("title"):
                    title_words = p["title"].split()[:6]
                    for w in title_words:
                        if len(w) >= 4 and w.lower() not in {
                            "attention",
                            "transformer",
                            "mechanism",
                            "using",
                            "based",
                            "with",
                            "from",
                        }:
                            entities.append(w)
            top_terms = list(dict.fromkeys(entities))[:5]
            label = f"cluster_{c_size}papers" + (
                f"_{'_'.join(top_terms[:2])}" if top_terms else ""
            )
            covered_aspects.append(label)

        # 4. LLM 分析覆盖度
        from ..services.llm_client import ainvoke_with_callbacks, create_llm

        cluster_descriptions = []
        for i, c in enumerate(clusters[:15]):
            c_size = len(c.get("paper_ids", []))
            sample_titles = []
            for pid in c.get("paper_ids", [])[:4]:
                p = next((x for x in papers if str(x.get("id")) == pid), None)
                if p:
                    sample_titles.append(str(p.get("title", ""))[:80])
            cluster_descriptions.append(
                f"社区{i + 1}: {c_size} papers, 示例: {'; '.join(sample_titles)}"
            )

        prompt = f"""研究主题: {topic}
目标论文数: {target_papers}
实际论文数: {len(paper_ids)}
聚类数: {len(clusters)}

聚类结果:
{chr(10).join(cluster_descriptions[:15])}

请分析:
1. 哪些研究子方向已被覆盖?
2. 哪些重要子方向仍缺失?
3. 如有缺失, 建议 2-3 个补充搜索查询。
4. 整体覆盖度评分 (0-1)。

返回严格 JSON: {{"covered_aspects": ["..."], "missing_aspects": ["..."], "suggested_new_queries": ["..."], "coverage_score": 0.X}}"""

        try:
            llm = create_llm(temperature=0.2, max_tokens=None)
            resp = await asyncio.wait_for(
                ainvoke_with_callbacks(
                    llm,
                    [
                        SystemMessage(
                            content="Return one JSON object only. No markdown."
                        ),
                        HumanMessage(content=prompt),
                    ],
                    timeout=60,
                ),
                timeout=90,
            )
            content = resp.content
            if isinstance(content, list):
                content = "".join(
                    b.get("text", "") if isinstance(b, dict) else str(b)
                    for b in content
                )
            analysis = json.loads(
                content.strip().replace("```json", "").replace("```", "").strip()
            )
            if not isinstance(analysis, dict):
                raise ValueError("coverage analysis must be a JSON object")
        except Exception:
            analysis = {
                "covered_aspects": covered_aspects[:5],
                "missing_aspects": [],
                "suggested_new_queries": [],
                "coverage_score": min(1.0, len(paper_ids) / max(1, target_papers)),
            }

        reported_score = _validated_coverage_score(analysis.get("coverage_score", 0.0))
        quantity_ceiling = min(1.0, len(paper_ids) / max(1, target_papers))
        coverage_score = max(0.0, min(1.0, reported_score, quantity_ceiling))

        # Replace only this project's derived clusters.
        await db.delete_project_clusters(project_id)
        saved_clusters = 0
        cluster_save_failures = 0
        for cluster in clusters:
            try:
                cluster["project_id"] = project_id
                cid = await db.save_cluster(cluster)
                c_paper_ids = cluster.get("paper_ids", [])
                if c_paper_ids:
                    await db.save_cluster_assignments(cid, c_paper_ids)
                saved_clusters += 1
            except Exception as e:
                cluster_save_failures += 1
                logger.debug("Cluster save failed", error=str(e)[:80])
        logger.info(
            "Clusters persisted to DB", saved=saved_clusters, total=len(clusters)
        )

        logger.info(
            "Cluster coverage analysis completed",
            clusters=len(clusters),
            coverage=coverage_score,
        )
        return json.dumps(
            {
                "cluster_count": len(clusters),
                "clusters": clusters,
                "total_papers": len(paper_ids),
                "covered_aspects": _normalized_text_items(
                    analysis.get("covered_aspects")
                ),
                "missing_aspects": _normalized_text_items(
                    analysis.get("missing_aspects")
                ),
                "suggested_new_queries": _normalized_text_items(
                    analysis.get("suggested_new_queries")
                ),
                "coverage_score": coverage_score,
                "cluster_save_failures": cluster_save_failures,
            },
            ensure_ascii=False,
        )

    except Exception as e:
        logger.error("Cluster coverage analysis failed", error=str(e)[:300])
        return json.dumps(
            {
                "error": str(e)[:200],
                "cluster_count": 0,
                "coverage_score": 0.0,
            },
            ensure_ascii=False,
        )


@tool
@_audited_agent_tool("analysis")
async def extract_knowledge_graph(
    papers_json: Annotated[str, "论文 JSON 数组字符串"],
) -> str:
    """从指定论文中提取知识图谱实体和关系。
    跳过已有 KG 实体的论文，并发处理当前执行中最多 80 篇核心论文。
    每篇有独立超时，返回值会报告因预算限制截断的论文数量。"""
    from ..agents.kg_extraction import extract_kg_from_papers_batch, normalize_kg
    from ..services.database import get_database

    try:
        all_papers = (
            json.loads(papers_json) if isinstance(papers_json, str) else papers_json
        )
    except (json.JSONDecodeError, TypeError):
        return json.dumps(
            {"entities": 0, "relations": 0, "error": "invalid papers_json"}
        )
    if not all_papers:
        return json.dumps({"entities": 0, "relations": 0, "status": "no_papers"})

    db = get_database()

    supplied_paper_ids = [
        str(paper.get("id") or "") for paper in all_papers if paper.get("id")
    ]

    # Inspect only KG rows linked to papers owned by this project execution.
    existing_ids: set[str] = set()
    try:
        async with db.session() as session:
            from sqlalchemy import text

            query_result = await session.execute(
                text("""
                    SELECT DISTINCT unnest(paper_ids)::text
                    FROM kg_entities
                    WHERE paper_ids && CAST(:paper_ids AS uuid[])
                """),
                {"paper_ids": supplied_paper_ids},
            )
            existing_ids = {str(r[0]) for r in query_result.fetchall() if r[0]}
    except Exception as lookup_error:
        logger.debug(
            "Existing KG lookup unavailable; extracting supplied papers",
            error=str(lookup_error)[:160],
        )

    fresh_papers = [p for p in all_papers if str(p.get("id", "")) not in existing_ids]
    if not fresh_papers:
        async with db.session() as session:
            from sqlalchemy import text

            count_result = await session.execute(
                text("""
                    SELECT
                        (SELECT COUNT(*) FROM kg_entities
                         WHERE paper_ids && CAST(:paper_ids AS uuid[])),
                        (SELECT COUNT(*) FROM kg_relations
                         WHERE paper_ids && CAST(:paper_ids AS uuid[]))
                """),
                {"paper_ids": supplied_paper_ids},
            )
            count_row = count_result.fetchone()
        return json.dumps(
            {
                "entity_count": int(count_row[0]) if count_row else 0,
                "relation_count": int(count_row[1]) if count_row else 0,
                "status": "all_done",
            }
        )

    processing_limit = 80
    truncated_count = max(0, len(fresh_papers) - processing_limit)
    fresh_papers = fresh_papers[:processing_limit]

    logger.info(
        "KG: %d papers skip, %d new — dispatching concurrent batches",
        len(all_papers) - len(fresh_papers),
        len(fresh_papers),
    )

    from ..config import get_settings

    # Per-run fan-out stays below the global LLM gate so one large project
    # cannot enqueue dozens of requests ahead of another admitted project.
    semaphore = asyncio.Semaphore(get_settings().agent_max_per_run_llm_requests)

    async def _work_one(
        paper: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        async with semaphore:
            result = await asyncio.wait_for(
                extract_kg_from_papers_batch(
                    [paper],
                    max_entities_per_paper=8,
                    max_relations_per_paper=8,
                ),
                timeout=300,
            )
            return (
                result.get("entities", []),
                result.get("relations", []),
            )

    results = await asyncio.gather(
        *(_work_one(paper) for paper in fresh_papers),
        return_exceptions=True,
    )
    all_entities: list[dict[str, Any]] = []
    all_relations: list[dict[str, Any]] = []
    failures = 0
    for work_result in results:
        if isinstance(work_result, BaseException):
            failures += 1
            logger.warning("KG paper extraction failed", error=str(work_result)[:160])
            continue
        entities, relations = work_result
        all_entities.extend(entities)
        all_relations.extend(relations)
    if failures == len(fresh_papers):
        raise RuntimeError("knowledge-graph extraction failed for every paper")

    normalized = normalize_kg(all_entities, all_relations)
    entities = normalized.get("entities", [])
    relations = normalized.get("relations", [])

    saved_e = 0
    persisted_entity_ids: dict[str, str] = {}
    if entities:
        try:
            await db.save_kg_entities(entities)
            normalized_names = [
                str(entity.get("normalized_name") or "")
                for entity in entities
                if entity.get("normalized_name")
            ]
            async with db.session() as session:
                from sqlalchemy import text

                id_result = await session.execute(
                    text("""
                        SELECT normalized_name, id
                        FROM kg_entities
                        WHERE normalized_name = ANY(CAST(:normalized_names AS text[]))
                    """),
                    {"normalized_names": normalized_names},
                )
                persisted_entity_ids = {
                    str(row[0]): str(row[1]) for row in id_result.fetchall()
                }
            saved_e = len(persisted_entity_ids)
        except Exception as e:
            logger.warning("KG entity persist failed", error=str(e)[:100])
    saved_r = 0
    unresolved_relations = 0
    if relations:
        bound_relations, unresolved_relations = _bind_kg_relation_entity_ids(
            relations,
            persisted_entity_ids,
        )
        try:
            saved_r = len(await db.save_kg_relations(bound_relations))
        except Exception as e:
            logger.warning("KG relation persist failed", error=str(e)[:100])

    logger.info(
        "KG done — concurrent batch extraction",
        total_papers=len(fresh_papers),
        entities=saved_e,
        relations=saved_r,
    )
    return json.dumps(
        {
            "entity_count": saved_e,
            "relation_count": saved_r,
            "status": "done",
            "processed_papers": len(fresh_papers),
            "truncated_papers": truncated_count,
            "unresolved_relations": unresolved_relations,
        },
        ensure_ascii=False,
    )


@tool
@_audited_agent_tool("analysis")
async def generate_evidence(
    papers_json: Annotated[str, "论文 JSON 数组"],
    topic: Annotated[str, "研究主题"],
) -> str:
    """为指定论文增量生成证据卡片。跳过已有卡片的论文。"""
    from ..agents.evidence_generation import generate_evidence_cards_batch
    from ..services.database import get_database
    from ..services.observability import get_current_project

    try:
        all_papers = (
            json.loads(papers_json) if isinstance(papers_json, str) else papers_json
        )
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"card_count": 0, "error": "invalid papers_json"})
    if not all_papers:
        return json.dumps({"card_count": 0, "status": "no_papers"})

    db = get_database()
    project_id = get_current_project()
    if not project_id:
        raise RuntimeError("generate_evidence requires project context")

    project_paper_ids = [
        str(paper.get("id") or paper.get("paper_id") or "")
        for paper in all_papers
        if paper.get("id") or paper.get("paper_id")
    ]
    existing_cards = await db.get_project_evidence_cards(
        project_id,
        paper_ids=project_paper_ids,
    )
    existing_cards = [
        card for card in existing_cards if not _is_fallback_evidence_card(card)
    ]
    existing_ids = {
        str(card.get("paper_id")) for card in existing_cards if card.get("paper_id")
    }

    fresh = [p for p in all_papers if str(p.get("id", "")) not in existing_ids]
    if not fresh:
        return json.dumps(
            {
                "card_count": len(existing_cards),
                "evidence_cards": existing_cards,
                "status": "all_done",
            },
            ensure_ascii=False,
            default=str,
        )

    logger.info("Evidence: %d skip, %d new", len(all_papers) - len(fresh), len(fresh))
    try:
        cards = await asyncio.wait_for(
            generate_evidence_cards_batch(fresh[:80]), timeout=900
        )
        saved = 0
        save_failures = 0
        fallback_count = 0
        for card in cards or []:
            try:
                if not isinstance(card, dict) or not card.get("paper_id"):
                    continue
                if _is_fallback_evidence_card(card):
                    fallback_count += 1
                    continue
                if card.get("paper_id"):
                    card["project_id"] = project_id
                    await db.save_evidence_card(card)
                    saved += 1
            except Exception as save_error:
                save_failures += 1
                logger.warning(
                    "Evidence card persist failed",
                    error=str(save_error)[:160],
                )
        logger.info("Evidence done", saved=saved, total=len(cards or []))
        all_cards = await db.get_project_evidence_cards(
            project_id,
            paper_ids=project_paper_ids,
        )
        all_cards = [card for card in all_cards if not _is_fallback_evidence_card(card)]
        claims = [
            str(card["claim"])[:120] for card in all_cards[:15] if card.get("claim")
        ]
        return json.dumps(
            {
                "card_count": len(all_cards),
                "key_claims": claims[:10],
                "evidence_cards": all_cards,
                "save_failures": save_failures,
                "fallback_count": fallback_count,
            },
            ensure_ascii=False,
            default=str,
        )
    except Exception as e:
        logger.error("Evidence generation failed", error=str(e)[:200])
        return json.dumps({"card_count": 0, "error": str(e)[:150]})


@tool
@_audited_agent_tool("analysis")
async def analyze_gaps_from_evidence(
    topic: Annotated[str, "研究主题"],
    evidence_count: Annotated[int, "已有证据卡片数量"],
    key_claims_json: Annotated[str, "关键发现 JSON 数组"],
) -> str:
    """基于已有证据卡片分析研究差距。返回 gap_analysis JSON。"""
    from ..services.llm_client import ainvoke_with_callbacks, create_llm

    try:
        claims = json.loads(key_claims_json)
    except (json.JSONDecodeError, TypeError):
        claims = []

    prompt = f"""研究主题: {topic}
证据卡片数量: {evidence_count}
关键发现: {json.dumps(claims[:15], ensure_ascii=False)}

分析研究差距。返回严格 JSON:
{{"identified_gaps": [{{"gap": "...", "priority": "high|medium|low"}}], "overall_completeness": 0.0-1.0}}"""

    try:
        llm = create_llm(temperature=0.2, max_tokens=None)
        result = await asyncio.wait_for(
            ainvoke_with_callbacks(
                llm,
                [
                    SystemMessage(content="Return one JSON object. No markdown."),
                    HumanMessage(content=prompt),
                ],
                timeout=60,
            ),
            timeout=90,
        )
        content = result.content
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        return json.dumps(
            json.loads(
                content.strip().replace("```json", "").replace("```", "").strip()
            ),
            ensure_ascii=False,
        )
    except Exception as error:
        return json.dumps(
            {
                "error": str(error)[:200],
                "identified_gaps": [],
                "overall_completeness": 0.0,
            }
        )


# =============================================================================
# Writing Team 工具
# =============================================================================


@tool
@_audited_agent_tool("writing")
async def generate_outline(
    topic: Annotated[str, "综述主题"],
    evidence_json: Annotated[str, "证据卡片摘要 JSON"],
    target_words: Annotated[int, "目标总字数"],
) -> str:
    """生成综述大纲。返回结构化大纲 JSON（标题 + 章节列表 + 每节目标字数和关键论点）。"""
    from ..services.llm_client import ainvoke_with_callbacks, create_llm

    try:
        evidence = (
            json.loads(evidence_json)
            if isinstance(evidence_json, str)
            else evidence_json
        )
    except (json.JSONDecodeError, TypeError):
        evidence = {}

    prompt = f"""研究主题：{topic}
目标字数：{target_words}

证据摘要：
{json.dumps(evidence, ensure_ascii=False)[:20000]}

请为这个主题生成学术综述大纲。
返回严格 JSON（至少 3 个章节）：
{{"title": "综述标题", "sections": [{{"title": "章节标题", "target_words": 2000, "key_points": ["论点1"]}}]}}"""

    try:
        llm = create_llm(temperature=0.3, max_tokens=None)
        result = await asyncio.wait_for(
            ainvoke_with_callbacks(
                llm,
                [
                    SystemMessage(content="Return ONE JSON object. No markdown."),
                    HumanMessage(content=prompt),
                ],
                timeout=120,
            ),
            timeout=150,
        )
        content = result.content
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        content = str(content).strip().replace("```json", "").replace("```", "").strip()
        s = content.find("{")
        e = content.rfind("}")
        if s != -1 and e > s:
            content = content[s : e + 1]
        outline = json.loads(content)
        if outline.get("sections"):
            return json.dumps(outline, ensure_ascii=False)
    except Exception as error:
        raise RuntimeError(f"outline generation failed: {error!s}") from error
    raise RuntimeError("outline generation returned no sections")


@tool
@_audited_agent_tool("writing")
async def write_section(
    topic: Annotated[str, "研究主题"],
    section_title: Annotated[str, "章节标题"],
    section_plan_json: Annotated[str, "章节计划 JSON"],
    available_papers_json: Annotated[str, "固定的项目引用编号映射 JSON"],
) -> str:
    """Write one section against the execution's immutable reference map."""

    from ..services.llm_client import ainvoke_with_callbacks, create_llm

    try:
        plan = (
            json.loads(section_plan_json)
            if isinstance(section_plan_json, str)
            else section_plan_json
        )
    except (json.JSONDecodeError, TypeError):
        plan = {}
    try:
        references = json.loads(available_papers_json)
    except (json.JSONDecodeError, TypeError) as error:
        raise ValueError("available_papers_json must be a JSON array") from error
    if not isinstance(references, list) or not references:
        raise ValueError("at least one project reference is required")

    target_words = plan.get("target_words", 2000)
    key_points = plan.get("key_points", [])

    ref_lines = []
    for reference in references:
        number = int(reference.get("number", 0))
        if number <= 0:
            continue
        title = str(reference.get("title") or "")[:120]
        authors = str(reference.get("authors") or "").strip()[:240]
        year = str(reference.get("year") or "")
        abstract = str(reference.get("abstract") or "")[:900]
        claims = reference.get("evidence_claims") or []
        claim_lines = "\n".join(
            f"    - evidence: {str(claim)[:400]}" for claim in claims[:3]
        )
        author_prefix = f"{authors}. " if authors else ""
        source = f"  [{number}] {author_prefix}{title} ({year})"
        if abstract:
            source += f"\n    abstract: {abstract}"
        if claim_lines:
            source += f"\n{claim_lines}"
        ref_lines.append(source)

    kp = "\n".join(f"- {k}" for k in key_points) if key_points else ""
    citation_guide = "\n".join(ref_lines) if ref_lines else ""
    kp_block = "关键论点：\n" + kp if kp else ""
    ref_block = "可用引用：\n" + citation_guide if citation_guide else "暂无引用"

    prompt = f"""研究主题：{topic}
章节标题：{section_title}
目标字数：{target_words}

{kp_block}

{ref_block}

请撰写该章节正文。要求：
- 学术论文风格，语言严谨客观
- 使用 [N] 格式引用
- 叙事引用必须写出可用引用中提供的第一作者，例如“王伟[7]提出”或“Smith等[7]发现”；禁止使用“[7]提出/认为/发现”作为句子开头
- 如果引用没有作者信息，改写为“已有研究提出……[N]”，不得臆造作者
- 只基于对应编号提供的摘要与证据陈述论点，不得虚构来源内容
- 每个主要论点后给出至少一个有效引用
- 不要输出章节标题，直接输出正文

只输出正文文本，不要 JSON。"""

    llm = create_llm(temperature=0.7, max_tokens=None)
    result = await asyncio.wait_for(
        ainvoke_with_callbacks(
            llm,
            [
                SystemMessage(content="你是学术综述写作专家。直接输出章节正文。"),
                HumanMessage(content=prompt),
            ],
            timeout=300,
        ),
        timeout=360,
    )
    content = result.content
    if isinstance(content, list):
        content = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in content
        )
    text = str(content).strip()
    if not text:
        raise RuntimeError("section writer returned empty content")
    return text


@tool
@_audited_agent_tool("writing")
async def revise_section(
    section_text: Annotated[str, "原始章节正文"],
    revision_instructions: Annotated[str, "修订指令"],
) -> str:
    """根据评审反馈修订章节。返回修订后的正文。"""
    from ..services.llm_client import ainvoke_with_callbacks, create_llm

    prompt = f"""修订以下章节正文。保持引用编号 [N] 不变，并保留已有作者与引用的绑定。
禁止使用“[N]提出/认为/发现”作为句子开头；缺少作者信息时改写为“已有研究提出……[N]”。直接输出修订后正文。

原始正文：{section_text[:30000]}

修订指令：{revision_instructions[:5000]}"""

    try:
        llm = create_llm(temperature=0.4, max_tokens=None)
        result = await asyncio.wait_for(
            ainvoke_with_callbacks(
                llm,
                [
                    SystemMessage(content="直接输出修订后正文。"),
                    HumanMessage(content=prompt),
                ],
                timeout=300,
            ),
            timeout=360,
        )
        content = result.content
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        return str(content)
    except Exception as error:
        raise RuntimeError(f"section revision failed: {error!s}") from error


# =============================================================================
# Peer Review Team 工具
# =============================================================================


@tool
@_audited_agent_tool("peer_review")
async def peer_review_survey(
    review_text: Annotated[str, "综述正文"],
    topic: Annotated[str, "研究主题"],
) -> str:
    """对综述进行同行评审。评估原创性、严谨性、一致性、引用质量等维度。
    返回结构化的评审报告 JSON，包含评分、优点、缺点和改进建议。"""
    from ..services.llm_client import ainvoke_with_callbacks, create_llm

    # ``run_peer_review`` already bounds each chunk. Never silently truncate a
    # chunk here, otherwise the caller can mistake a partial review for a full
    # document quality assessment.
    text_sample = review_text or ""

    prompt = f"""研究主题: {topic}

综述正文:
{text_sample}

请基于以下维度进行全面评审，返回严格 JSON:

{{
  "overall_score": 0-100,
  "summary": "总体评价（1-2句话）",
  "strengths": ["优点1", "优点2"],
  "weaknesses": ["缺点1", "缺点2"],
  "suggestions": ["改进建议1", "改进建议2"],
  "dimension_scores": {{
    "originality": {{"score": 0-100, "comment": ""}},
    "rigor": {{"score": 0-100, "comment": ""}},
    "consistency": {{"score": 0-100, "comment": ""}},
    "completeness": {{"score": 0-100, "comment": ""}},
    "citations": {{"score": 0-100, "comment": ""}}
  }}
}}

规则：
- 输出严格 JSON，不要 markdown
- 评分基于学术标准，60 分以上为合格
- 诚实评估，发现不足，保持建设性
"""

    try:
        llm = create_llm(temperature=0.2, max_tokens=None)
        result = await ainvoke_with_callbacks(
            llm,
            [
                SystemMessage(content="Return one JSON object. No markdown."),
                HumanMessage(content=prompt),
            ],
            timeout=120,
        )
        content = result.content
        if isinstance(content, list):
            content = "".join(
                b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            )
        # 清理可能的 think 标签
        import re as _re

        content = _re.sub(
            r"<think\b[^>]*>.*?</think\s*>", "", content, flags=_re.DOTALL
        )
        content = _re.sub(r"</think\s*>", "", content)
        # 提取 JSON
        s = content.find("{")
        e = content.rfind("}")
        if s != -1 and e > s:
            content = content[s : e + 1]
        report = json.loads(content.strip())
        logger.info("Peer review completed", score=report.get("overall_score", 0))
        return json.dumps(report, ensure_ascii=False)
    except Exception as error:
        raise RuntimeError(f"peer review failed: {error!s}") from error
