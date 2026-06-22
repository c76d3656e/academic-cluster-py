"""
Initial community detection node.

This stage runs before KG/evidence generation and uses only reranked papers
plus KNN quality edges to form communities and select core/auxiliary papers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from ...services.database import get_database
from ...services.vector_store import get_vector_store
from ...tools.clustering import build_hybrid_graph, community_detection
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()


def _paper_year(paper: dict) -> int:
    value = paper.get("year") or paper.get("publication_date")
    if value:
        try:
            return int(str(value)[:4])
        except (TypeError, ValueError):
            return 0
    return 0


def _paper_rank_score(paper: dict, centrality: float = 0.0) -> float:
    from .rerank import _compute_quality_score

    quality = paper.get("quality_score")
    if quality is None:
        quality = _compute_quality_score(paper)
    try:
        quality = float(quality)
    except (TypeError, ValueError):
        quality = 0.0

    try:
        citations = max(0, int(paper.get("citation_count") or 0))
    except (TypeError, ValueError):
        citations = 0
    citation_score = min(1.0, citations / 500.0)

    year = _paper_year(paper)
    current_year = datetime.now().year
    recency = 0.0
    if year:
        recency = max(0.0, min(1.0, (year - 2015) / max(1, current_year - 2015)))

    return quality * 0.55 + centrality * 0.25 + citation_score * 0.12 + recency * 0.08


def select_community_balanced_papers(
    clusters: list[dict],
    reranked_papers: list[dict],
    core_count: int = 160,
    auxiliary_count: int = 160,
) -> tuple[list[str], list[str]]:
    """Select core papers with minimum per-community coverage and proportional allocation."""
    if core_count <= 0:
        return [], []

    paper_by_id = {str(p.get("id")): p for p in reranked_papers if p.get("id")}
    rerank_order = {
        str(p.get("id")): idx for idx, p in enumerate(reranked_papers) if p.get("id")
    }
    eligible_clusters = [
        c
        for c in clusters
        if any(str(pid) in paper_by_id for pid in (c.get("paper_ids") or []))
    ]

    if not eligible_clusters:
        core = [str(p.get("id")) for p in reranked_papers[:core_count] if p.get("id")]
        auxiliary = [
            str(p.get("id"))
            for p in reranked_papers
            if p.get("id") and str(p.get("id")) not in set(core)
        ][:auxiliary_count]
        return core, auxiliary

    centrality_by_paper: dict[str, float] = {}
    for cluster in eligible_clusters:
        paper_ids = [
            str(pid)
            for pid in cluster.get("paper_ids") or []
            if str(pid) in paper_by_id
        ]
        size = max(1, len(paper_ids))
        for idx, pid in enumerate(paper_ids):
            centrality_by_paper[pid] = max(
                centrality_by_paper.get(pid, 0.0),
                1.0 - (idx / size),
            )

    allocations = {str(c.get("id")): 0 for c in eligible_clusters}
    for cluster in eligible_clusters[: min(len(eligible_clusters), core_count)]:
        allocations[str(cluster.get("id"))] = 1

    remaining = core_count - sum(allocations.values())
    total_size = sum(len(c.get("paper_ids") or []) for c in eligible_clusters) or 1
    fractional: list[tuple[float, str]] = []
    for cluster in eligible_clusters:
        cid = str(cluster.get("id"))
        size = len(cluster.get("paper_ids") or [])
        if size <= 0:
            continue
        raw = remaining * (size / total_size)
        extra = int(raw)
        allocations[cid] += extra
        fractional.append((raw - extra, cid))

    while sum(allocations.values()) < core_count and fractional:
        fractional.sort(reverse=True)
        _, cid = fractional.pop(0)
        allocations[cid] += 1

    selected: list[str] = []
    seen: set[str] = set()
    for cluster in eligible_clusters:
        cid = str(cluster.get("id"))
        quota = allocations.get(cid, 0)
        if quota <= 0:
            continue
        candidates = [
            str(pid)
            for pid in cluster.get("paper_ids") or []
            if str(pid) in paper_by_id and str(pid) not in seen
        ]
        candidates.sort(
            key=lambda pid: (
                _paper_rank_score(paper_by_id[pid], centrality_by_paper.get(pid, 0.0)),
                -rerank_order.get(pid, 10**9),
            ),
            reverse=True,
        )
        for pid in candidates[:quota]:
            selected.append(pid)
            seen.add(pid)

    if len(selected) < core_count:
        for paper in reranked_papers:
            pid = str(paper.get("id"))
            if pid and pid not in seen:
                selected.append(pid)
                seen.add(pid)
            if len(selected) >= core_count:
                break

    selected = selected[:core_count]
    selected_set = set(selected)
    auxiliary = [
        str(p.get("id"))
        for p in reranked_papers
        if p.get("id") and str(p.get("id")) not in selected_set
    ][:auxiliary_count]
    return selected, auxiliary


async def community_detection_node(state: PipelineState) -> dict:
    """Run initial community detection without KG/evidence and choose core 160."""
    config = state.config or {}
    algorithm = config.get("clustering_algorithm", "leiden")
    resolution = config.get("clustering_resolution", 1.0)
    raw_weights = config.get("hybrid_graph_weights", {}) or {}
    weights = {
        "knn": raw_weights.get("knn", 0.95),
        "kg_relation": 0.0,
        "shared_entity": 0.0,
        "evidence": 0.0,
        "quality": raw_weights.get("quality", 0.05),
    }

    logger.info(
        "Starting initial community detection",
        algorithm=algorithm,
        reranked_count=len(state.reranked_paper_ids),
    )

    db = get_database()
    vector_store = get_vector_store()

    try:
        all_paper_ids = state.reranked_paper_ids or list(dict.fromkeys(state.paper_ids))
        knn_edges = await vector_store.get_knn_graph(
            paper_ids=all_paper_ids, k=10, threshold=0.3
        )
        hybrid_graph = build_hybrid_graph(
            knn_edges=knn_edges,
            kg_relations=[],
            kg_entities=[],
            evidence_cards=[],
            core_paper_ids=all_paper_ids,
            weights=weights,
        )

        clusters = community_detection(
            graph=hybrid_graph,
            algorithm=algorithm,
            resolution=resolution,
            seed=42,
        )

        cluster_ids: list[str] = []
        saved_clusters: list[dict[str, Any]] = []
        for cluster in clusters:
            cluster["project_id"] = state.project_id
            cluster.setdefault("algorithm", algorithm)
            cluster.setdefault("parameters", {"resolution": resolution, "pre_kg": True})
            cluster_id = await db.save_cluster(cluster)
            cluster["id"] = cluster_id
            cluster_ids.append(cluster_id)
            saved_clusters.append(cluster)
            paper_ids = cluster.get("paper_ids", [])
            if paper_ids:
                await db.save_cluster_assignments(cluster_id, paper_ids)

        core_count = int(config.get("core_reference_count", 160))
        auxiliary_count = int(config.get("auxiliary_reference_count", 160))
        reranked_papers = await db.get_papers_by_ids(state.reranked_paper_ids)
        core_paper_ids, auxiliary_paper_ids = select_community_balanced_papers(
            clusters=saved_clusters,
            reranked_papers=reranked_papers,
            core_count=core_count,
            auxiliary_count=auxiliary_count,
        )

        logger.info(
            "Initial community detection completed",
            clusters=len(cluster_ids),
            total_nodes=hybrid_graph.number_of_nodes(),
            total_edges=hybrid_graph.number_of_edges(),
            core_count=len(core_paper_ids),
            auxiliary_count=len(auxiliary_paper_ids),
            pre_kg=True,
            community_balanced=True,
        )

        await send_progress(
            state.project_id,
            "community_detection",
            f"发现 {len(cluster_ids)} 个研究社区，核心 {len(core_paper_ids)} 篇，辅助 {len(auxiliary_paper_ids)} 篇",
            detail={
                "cluster_count": len(cluster_ids),
                "total_nodes": hybrid_graph.number_of_nodes(),
                "total_edges": hybrid_graph.number_of_edges(),
                "core_count": len(core_paper_ids),
                "auxiliary_count": len(auxiliary_paper_ids),
                "pre_kg": True,
                "community_balanced": True,
            },
        )

        return {
            "cluster_ids": cluster_ids,
            "hybrid_graph_id": f"initial_knn_{state.project_id}",
            "core_paper_ids": core_paper_ids,
            "auxiliary_paper_ids": auxiliary_paper_ids,
            "status": "clustered",
            "gap_reports": [],
        }

    except Exception as e:
        logger.error("Community detection failed", error=str(e))
        raise
