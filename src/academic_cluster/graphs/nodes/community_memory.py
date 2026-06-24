"""Community memory synthesis node."""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime
from typing import Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from ...services.database import get_database
from ...services.llm_client import ainvoke_with_callbacks, create_llm
from ...services.provider_pool import get_llm_available_slots
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()

DEFAULT_COMMUNITY_MEMORY_CONCURRENCY_CAP = 8
DEFAULT_COMMUNITY_MEMORY_TIMEOUT_S = 90
DEFAULT_COMMUNITY_MEMORY_LLM_LIMIT = 16


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _paper_year(paper: dict[str, Any]) -> int:
    value = paper.get("year") or paper.get("publication_date")
    if value:
        try:
            return int(str(value)[:4])
        except (TypeError, ValueError):
            return 0
    return 0


def _top_unique(values: list[Any], limit: int = 8) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value or "").split())
        if text and text.lower() not in seen:
            result.append(text)
            seen.add(text.lower())
        if len(result) >= limit:
            break
    return result


def _json_text(value: Any, max_chars: int = 800) -> str:
    text = " ".join(str(value or "").split())
    return text[:max_chars]


def _parse_json_object(content: Any) -> dict[str, Any]:
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
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise
        value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("LLM response is not a JSON object")
    return value


def _int_config(config: dict[str, Any] | None, key: str, default: int) -> int:
    value = (config or {}).get(key, default)
    if isinstance(value, str) and value.strip().lower() in {"auto", ""}:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_memory_enrichment(
    raw: dict[str, Any], fallback: dict[str, Any]
) -> dict[str, Any]:
    """Normalize LLM community synthesis while preserving deterministic IDs."""
    enriched = dict(fallback)
    metadata = dict(enriched.get("metadata") or {})

    summary = _json_text(raw.get("community_summary") or raw.get("summary"), 1200)
    if summary:
        enriched["summary"] = summary

    for field, limit in (
        ("method_families", 10),
        ("limitations", 10),
        ("future_directions", 8),
    ):
        values = raw.get(field)
        if isinstance(values, list):
            cleaned = _top_unique(values, limit)
            if cleaned:
                enriched[field] = cleaned

    claims = raw.get("representative_claims") or raw.get("key_claims")
    normalized_claims = []
    if isinstance(claims, list):
        for item in claims[:12]:
            if isinstance(item, dict):
                claim = _json_text(item.get("claim"), 600)
                if not claim:
                    continue
                normalized_claims.append(
                    {
                        "paper_id": str(item.get("paper_id") or ""),
                        "claim": claim,
                        "evidence_card_id": str(item.get("evidence_card_id") or ""),
                        "support": _json_text(
                            item.get("support") or item.get("evidence_span"), 500
                        ),
                        "synthesis_role": _json_text(item.get("synthesis_role"), 200),
                    }
                )
            else:
                text = _json_text(item, 600)
                if text:
                    normalized_claims.append({"paper_id": "", "claim": text})
    if normalized_claims:
        enriched["key_claims"] = normalized_claims

    cohesion = raw.get("coherence_assessment") or raw.get("coherence")
    if isinstance(cohesion, dict):
        metadata["coherence_assessment"] = {
            "score": cohesion.get("score"),
            "rationale": _json_text(cohesion.get("rationale"), 500),
            "outlier_paper_ids": [
                str(pid) for pid in cohesion.get("outlier_paper_ids", [])[:12]
            ]
            if isinstance(cohesion.get("outlier_paper_ids"), list)
            else [],
        }

    topic_relevance = raw.get("topic_relevance")
    if isinstance(topic_relevance, dict):
        metadata["topic_relevance"] = {
            "score": topic_relevance.get("score"),
            "rationale": _json_text(topic_relevance.get("rationale"), 500),
        }

    evidence_gaps = raw.get("evidence_gaps")
    if isinstance(evidence_gaps, list):
        metadata["evidence_gaps"] = _top_unique(evidence_gaps, 8)

    metadata["synthesis_mode"] = "llm_enriched"
    enriched["metadata"] = metadata
    return enriched


def _compute_cross_community_links(
    clusters: list[dict[str, Any]],
    kg_entities: list[dict[str, Any]],
    top_k: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    """Deterministic cross-community link discovery via shared KG entities.

    For each cluster, finds other clusters that share the most KG entities.
    Returns {cluster_id: [{cluster_id, shared_entities, weight}, ...]}.
    """
    entity_names: dict[str, str] = {}

    # Build cluster_id → set of paper_ids
    cluster_paper_map: dict[str, set[str]] = {}
    for cluster in clusters:
        cid = str(cluster.get("id"))
        pids = {str(pid) for pid in _as_list(cluster.get("paper_ids"))}
        cluster_paper_map[cid] = pids

    # Build entity → cluster_ids by checking which clusters contain the entity's papers
    entity_to_clusters: dict[str, set[str]] = {}
    for entity in kg_entities:
        eid = str(entity.get("id") or entity.get("name", ""))
        if not eid:
            continue
        name = str(entity.get("name", ""))
        entity_names[eid] = name
        ent_paper_ids = {str(pid) for pid in _as_list(entity.get("paper_ids"))}
        if not ent_paper_ids:
            continue
        for cid, c_papers in cluster_paper_map.items():
            if ent_paper_ids & c_papers:
                entity_to_clusters.setdefault(eid, set()).add(cid)

    # For each cluster, count shared entities with every other cluster
    links: dict[str, list[dict[str, Any]]] = {}
    for cluster in clusters:
        cid = str(cluster.get("id"))
        neighbor_counts: dict[
            str, list[str]
        ] = {}  # neighbor_cid → [shared entity names]
        for eid, cluster_set in entity_to_clusters.items():
            if cid not in cluster_set:
                continue
            ename = entity_names.get(eid, eid)
            for neighbor_cid in cluster_set:
                if neighbor_cid == cid:
                    continue
                neighbor_counts.setdefault(neighbor_cid, []).append(ename)

        sorted_neighbors = sorted(
            neighbor_counts.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        )[:top_k]

        links[cid] = [
            {
                "cluster_id": neighbor_cid,
                "shared_entities": shared[:8],
                "weight": len(shared),
            }
            for neighbor_cid, shared in sorted_neighbors
            if shared
        ]

    return links


def synthesize_community_memory(
    *,
    project_id: str,
    cluster: dict[str, Any],
    papers: list[dict[str, Any]],
    evidence_cards: list[dict[str, Any]],
    kg_entities: list[dict[str, Any]],
    kg_relations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build deterministic structured memory for one community."""
    cluster_id = str(cluster.get("id"))
    paper_by_id = {str(p.get("id")): p for p in papers if p.get("id")}
    cluster_paper_ids = [str(pid) for pid in cluster.get("paper_ids") or []]
    cluster_papers = [
        paper_by_id[pid] for pid in cluster_paper_ids if pid in paper_by_id
    ]

    cards = [
        c for c in evidence_cards if str(c.get("paper_id")) in set(cluster_paper_ids)
    ]
    entities = [
        e
        for e in kg_entities
        if {str(pid) for pid in _as_list(e.get("paper_ids"))} & set(cluster_paper_ids)
    ]
    relations = [
        r
        for r in kg_relations
        if {str(pid) for pid in _as_list(r.get("paper_ids"))} & set(cluster_paper_ids)
    ]

    method_values = [c.get("method") for c in cards]
    method_values.extend(
        e.get("name")
        for e in entities
        if str(e.get("entity_type", "")).lower()
        in {"method", "model", "framework", "algorithm", "technique", "approach"}
    )
    method_families = _top_unique(method_values, 10)

    key_claims = [
        {
            "paper_id": str(c.get("paper_id")),
            "claim": c.get("claim"),
            "evidence_card_id": str(c.get("id")),
        }
        for c in cards
        if c.get("claim")
    ][:12]
    limitations = _top_unique([c.get("limitation") for c in cards], 10)
    if not limitations:
        limitations = _top_unique(
            [
                e.get("name")
                for e in entities
                if str(e.get("entity_type", "")).lower()
                in {"limitation", "open_problem", "open problem"}
            ]
        )

    future_directions = [f"Address limitation: {item}" for item in limitations[:5]] or [
        "Clarify open problems through stronger comparative evidence."
    ]

    sorted_papers = sorted(
        cluster_papers,
        key=lambda p: (int(p.get("citation_count") or 0), _paper_year(p)),
        reverse=True,
    )
    current_year = datetime.now().year
    foundation = [
        str(p.get("id"))
        for p in sorted_papers
        if _paper_year(p) and _paper_year(p) <= current_year - 8
    ][:8]
    frontier = [
        str(p.get("id"))
        for p in sorted_papers
        if _paper_year(p) and _paper_year(p) >= current_year - 3
    ][:8]
    development = [
        str(p.get("id"))
        for p in sorted_papers
        if str(p.get("id")) not in set(foundation + frontier)
    ][:8]
    representative = [str(p.get("id")) for p in sorted_papers[:12]]

    proof_ids = []
    for card in cards:
        if card.get("id"):
            proof_ids.append(
                {
                    "type": "evidence_card",
                    "id": str(card["id"]),
                    "paper_id": str(card.get("paper_id")),
                }
            )
    for pid in representative:
        proof_ids.append({"type": "paper", "id": pid})

    relation_counts = Counter(
        str(r.get("relation_type")) for r in relations if r.get("relation_type")
    )
    entity_counts = Counter(
        str(e.get("entity_type")) for e in entities if e.get("entity_type")
    )
    top_titles = _top_unique([p.get("title") for p in sorted_papers], 3)
    summary = (
        f"Community with {len(cluster_paper_ids)} papers. "
        f"Representative work centers on {', '.join(method_families[:4]) or 'related methods'}"
        f" with claims from {len(cards)} evidence cards."
    )
    if top_titles:
        summary += " Representative papers include " + "; ".join(top_titles) + "."

    return {
        "project_id": project_id,
        "cluster_id": cluster_id,
        "summary": summary,
        "method_families": method_families,
        "key_claims": key_claims,
        "limitations": limitations,
        "future_directions": future_directions,
        "foundation_papers": foundation,
        "development_papers": development,
        "frontier_papers": frontier,
        "representative_papers": representative,
        "cross_community_links": [],
        "proof_ids": proof_ids,
        "metadata": {
            "paper_count": len(cluster_paper_ids),
            "evidence_card_count": len(cards),
            "kg_entity_count": len(entities),
            "kg_relation_count": len(relations),
            "entity_type_counts": dict(entity_counts),
            "relation_type_counts": dict(relation_counts),
        },
    }


async def enrich_community_memory_with_llm(
    *,
    topic: str,
    fallback_memory: dict[str, Any],
    cluster: dict[str, Any],
    papers: list[dict[str, Any]],
    evidence_cards: list[dict[str, Any]],
    kg_entities: list[dict[str, Any]],
    kg_relations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Produce SurveyG-style community synthesis from KG and evidence cards."""
    cluster_paper_ids = {str(pid) for pid in cluster.get("paper_ids") or []}
    cluster_papers = [p for p in papers if str(p.get("id")) in cluster_paper_ids][:24]
    cards = [c for c in evidence_cards if str(c.get("paper_id")) in cluster_paper_ids][
        :24
    ]
    entities = [
        e
        for e in kg_entities
        if {str(pid) for pid in _as_list(e.get("paper_ids"))} & cluster_paper_ids
    ][:40]
    relations = [
        r
        for r in kg_relations
        if {str(pid) for pid in _as_list(r.get("paper_ids"))} & cluster_paper_ids
    ][:30]

    paper_lines = []
    for p in cluster_papers:
        paper_lines.append(
            {
                "paper_id": str(p.get("id")),
                "title": _json_text(p.get("title"), 180),
                "year": _paper_year(p) or None,
                "abstract": _json_text(p.get("abstract"), 450),
                "citation_count": p.get("citation_count"),
            }
        )
    card_lines = []
    for c in cards:
        card_lines.append(
            {
                "evidence_card_id": str(c.get("id") or ""),
                "paper_id": str(c.get("paper_id") or ""),
                "claim": _json_text(c.get("claim"), 450),
                "evidence_span": _json_text(c.get("evidence_span"), 450),
                "method": _json_text(c.get("method"), 220),
                "metric": _json_text(c.get("metric"), 220),
                "limitation": _json_text(c.get("limitation"), 220),
                "confidence": c.get("confidence"),
            }
        )
    entity_lines = [
        {
            "name": _json_text(e.get("name"), 120),
            "type": _json_text(e.get("entity_type"), 80),
            "paper_ids": [str(pid) for pid in _as_list(e.get("paper_ids"))[:8]],
        }
        for e in entities
    ]
    relation_lines = [
        {
            "type": _json_text(r.get("relation_type"), 80),
            "paper_ids": [str(pid) for pid in _as_list(r.get("paper_ids"))[:8]],
        }
        for r in relations
    ]

    from ...prompts import get_community_memory_prompt

    prompt_template = get_community_memory_prompt()
    prompt = prompt_template.format(
        topic=topic,
        cluster_id=cluster.get("id"),
        cluster_name=cluster.get("name", ""),
        papers=json.dumps(paper_lines, ensure_ascii=False),
        evidence_cards=json.dumps(card_lines, ensure_ascii=False),
        kg_entities=json.dumps(entity_lines, ensure_ascii=False),
        kg_relations=json.dumps(relation_lines, ensure_ascii=False),
    )

    llm = create_llm(temperature=0.2, max_tokens=2200)
    response = await ainvoke_with_callbacks(
        llm,
        [
            SystemMessage(
                content="You synthesize academic literature communities. Return only strict JSON."
            ),
            HumanMessage(content=prompt),
        ],
        timeout=240,
    )
    raw = _parse_json_object(response.content)
    return _normalize_memory_enrichment(raw, fallback_memory)


async def community_memory_node(state: PipelineState) -> dict[str, Any]:
    """Persist one structured memory per cluster."""
    db = get_database()
    logger.info("Starting community memory synthesis", clusters=len(state.cluster_ids))

    clusters = await db.get_clusters_by_ids(state.cluster_ids)

    # === 幂等恢复：查询已有社区记忆，跳过已处理的 cluster ===
    existing_memory_ids: list[str] = []
    already_done_cluster_ids: set[str] = set()
    try:
        existing_memories = await db.get_community_memories_by_project(state.project_id)
        existing_memory_ids = [str(m["id"]) for m in existing_memories if m.get("id")]
        cluster_id_set = {str(c.get("id")) for c in clusters if c.get("id")}
        already_done_cluster_ids = {
            str(m["cluster_id"])
            for m in existing_memories
            if m.get("cluster_id") and str(m["cluster_id"]) in cluster_id_set
        }
        if already_done_cluster_ids:
            logger.info(
                "Resuming community memory, skipping already processed clusters",
                already_done=len(already_done_cluster_ids),
                total=len(clusters),
            )
    except Exception as e:
        logger.warning(
            "Failed to check existing community memories, processing all", error=str(e)
        )
        already_done_cluster_ids = set()

    # 过滤掉已处理的 cluster
    remaining_clusters = [
        c for c in clusters if str(c.get("id")) not in already_done_cluster_ids
    ]
    if not remaining_clusters:
        logger.info("All clusters already have community memories, skipping")
        return {
            "community_memory_ids": existing_memory_ids,
            "status": "community_memory_synthesized",
        }

    all_paper_ids = list(
        dict.fromkeys((state.core_paper_ids or []) + (state.auxiliary_paper_ids or []))
    )
    papers = await db.get_papers_by_ids(all_paper_ids)
    evidence_cards = await db.get_evidence_cards_by_ids(state.evidence_card_ids)
    kg_entities = await db.get_kg_entities_by_ids(state.kg_entity_ids)
    kg_relations = await db.get_kg_relations_by_ids(state.kg_relation_ids)

    def _cluster_size(cluster: dict[str, Any]) -> int:
        return len(cluster.get("paper_ids") or [])

    llm_limit = max(
        0,
        _int_config(
            state.config,
            "community_memory_llm_limit",
            DEFAULT_COMMUNITY_MEMORY_LLM_LIMIT,
        ),
    )
    llm_cluster_ids = {
        str(cluster.get("id"))
        for cluster in sorted(clusters, key=_cluster_size, reverse=True)[:llm_limit]
    }

    async def _build_memory(cluster: dict[str, Any]) -> dict[str, Any]:
        fallback = synthesize_community_memory(
            project_id=state.project_id,
            cluster=cluster,
            papers=papers,
            evidence_cards=evidence_cards,
            kg_entities=kg_entities,
            kg_relations=kg_relations,
        )
        if str(cluster.get("id")) not in llm_cluster_ids:
            metadata = dict(fallback.get("metadata") or {})
            metadata["synthesis_mode"] = "deterministic_fallback"
            metadata["llm_skipped"] = "community_memory_llm_limit"
            fallback["metadata"] = metadata
            return fallback
        try:
            timeout_s = max(
                1,
                _int_config(
                    state.config,
                    "community_memory_timeout_s",
                    DEFAULT_COMMUNITY_MEMORY_TIMEOUT_S,
                ),
            )
            return await asyncio.wait_for(
                enrich_community_memory_with_llm(
                    topic=state.query,
                    fallback_memory=fallback,
                    cluster=cluster,
                    papers=papers,
                    evidence_cards=evidence_cards,
                    kg_entities=kg_entities,
                    kg_relations=kg_relations,
                ),
                timeout=timeout_s,
            )
        except TimeoutError:
            metadata = dict(fallback.get("metadata") or {})
            metadata["synthesis_mode"] = "deterministic_fallback"
            metadata["llm_error"] = "community memory enrichment timed out"
            fallback["metadata"] = metadata
            logger.warning(
                "Community LLM synthesis timed out, using deterministic fallback",
                cluster_id=cluster.get("id"),
                timeout_s=timeout_s,
            )
            return fallback
        except Exception as e:
            metadata = dict(fallback.get("metadata") or {})
            metadata["synthesis_mode"] = "deterministic_fallback"
            metadata["llm_error"] = str(e)[:300]
            fallback["metadata"] = metadata
            logger.warning(
                "Community LLM synthesis failed, using deterministic fallback",
                cluster_id=cluster.get("id"),
                error=str(e),
            )
            return fallback

    requested_concurrency = _int_config(
        state.config, "community_memory_concurrency", -1
    )
    provider_slots = get_llm_available_slots(default=10)
    if requested_concurrency <= 0:
        concurrency = min(provider_slots, DEFAULT_COMMUNITY_MEMORY_CONCURRENCY_CAP)
    else:
        concurrency = min(requested_concurrency, provider_slots)
    logger.info(
        "Community memory concurrency resolved",
        requested=requested_concurrency,
        provider_slots=provider_slots,
        effective=concurrency,
        llm_limit=llm_limit,
        clusters=len(remaining_clusters),
        skipped=len(already_done_cluster_ids),
    )
    semaphore = asyncio.Semaphore(max(1, concurrency))
    completed_count = 0
    total_to_process = len(remaining_clusters)
    completed_lock = asyncio.Lock()

    async def _bounded(idx: int, cluster: dict[str, Any]) -> dict[str, Any]:
        nonlocal completed_count
        async with semaphore:
            result = await _build_memory(cluster)
        async with completed_lock:
            completed_count += 1
            await send_progress(
                state.project_id,
                "community_memory",
                f"社区记忆聚合中 {completed_count}/{total_to_process}...",
                progress=completed_count / total_to_process
                if total_to_process > 0
                else 0,
            )
        return result

    memories = await asyncio.gather(
        *[_bounded(i, cluster) for i, cluster in enumerate(remaining_clusters)]
    )

    # === 跨聚类关联计算（确定性，基于共享 KG 实体） ===
    cross_links = _compute_cross_community_links(clusters, kg_entities)
    for memory in memories:
        cid = str(memory.get("cluster_id", ""))
        memory["cross_community_links"] = cross_links.get(cid, [])
    logger.info(
        "Cross-community links computed",
        clusters_with_links=sum(1 for v in cross_links.values() if v),
        total_links=sum(len(v) for v in cross_links.values()),
    )

    new_memory_ids: list[str] = []
    for memory in memories:
        new_memory_ids.append(await db.save_community_memory(memory))

    # 合并已有 + 新生成的
    all_memory_ids = existing_memory_ids + new_memory_ids

    # 回填已有记忆中空的 cross_community_links
    if already_done_cluster_ids:
        all_memories = await db.get_community_memories_by_project(state.project_id)
        backfilled = 0
        for mem in all_memories:
            if str(mem.get("cluster_id")) in cross_links and not mem.get(
                "cross_community_links"
            ):
                mem["cross_community_links"] = cross_links[str(mem["cluster_id"])]
                await db.save_community_memory(mem)
                backfilled += 1
        if backfilled:
            logger.info(
                "Backfilled cross_community_links for existing memories",
                count=backfilled,
            )

    await send_progress(
        state.project_id,
        "community_memory",
        f"社区记忆生成完成，共 {len(all_memory_ids)} 个",
        detail={"community_memory_count": len(all_memory_ids)},
    )

    logger.info(
        "Community memory synthesis completed",
        new=len(new_memory_ids),
        total=len(all_memory_ids),
        skipped=len(already_done_cluster_ids),
    )
    return {
        "community_memory_ids": all_memory_ids,
        "status": "community_memory_synthesized",
    }
