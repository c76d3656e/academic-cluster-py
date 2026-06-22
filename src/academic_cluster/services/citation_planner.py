"""
Citation Planner - 为综述论文各章节分配候选参考文献

对齐 Rust 版 Prism 的 8 层优先级系统：
1. CommunityCore          - 主聚类中的核心文献
2. CommunityAuxiliary      - 主聚类中的辅助文献
3. HybridNeighborCore     - 混合图邻居中的核心文献（跨聚类桥接）
4. HybridNeighborAuxiliary - 混合图邻居中的辅助文献
5. RemainingCommunityCore - 剩余聚类中的核心文献
6. RemainingCommunityAuxiliary - 剩余聚类中的辅助文献
7. GlobalCore             - 全局核心文献（兜底）
8. GlobalAuxiliary        - 全局辅助文献（兜底）
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CandidateSelectionSource(StrEnum):
    """候选文献的选取来源（优先级从高到低，对齐 Rust 版）"""
    COMMUNITY_CORE = "community_core"
    COMMUNITY_AUXILIARY = "community_auxiliary"
    HYBRID_NEIGHBOR_CORE = "hybrid_neighbor_core"
    HYBRID_NEIGHBOR_AUXILIARY = "hybrid_neighbor_auxiliary"
    REMAINING_CORE = "remaining_core"
    REMAINING_AUXILIARY = "remaining_auxiliary"
    GLOBAL_CORE = "global_core"
    GLOBAL_AUXILIARY = "global_auxiliary"


@dataclass
class NearbyHybridCandidate:
    """混合图中的跨聚类邻居候选"""
    index: int              # 论文在 papers 列表中的索引
    anchor_index: int       # 锚点论文（社区内论文）的索引
    weight: float           # 混合图边权重
    rank: int               # 边的排名


@dataclass
class SectionCitationCandidate:
    """单篇候选文献的详细信息"""
    paper_id: str
    cluster_id: int | None
    is_core: bool
    source: CandidateSelectionSource
    hybrid_anchor_paper_id: str | None = None
    hybrid_weight_basis_points: int | None = None


@dataclass
class SectionCitationPlan:
    """一个章节的引用分配计划"""
    section_index: int
    section_title: str
    key_clusters: list[int]
    candidate_paper_ids: list[str]       # 按优先级排序的论文 ID
    candidate_details: list[dict]        # 论文详情，用于渲染

    @property
    def primary_paper_ids(self) -> list[str]:
        """核心文献 ID 列表"""
        return [
            d["paper_id"] for d in self.candidate_details if d["is_core"]
        ]

    @property
    def secondary_paper_ids(self) -> list[str]:
        """辅助文献 ID 列表"""
        return [
            d["paper_id"] for d in self.candidate_details if not d["is_core"]
        ]


def _fallback_section_clusters(
    section_index: int,
    section_count: int,
    target: int,
    ordered_clusters: list[int],
    cluster_counts: dict[int, int],
) -> list[int]:
    """
    对齐 Rust 版 fallback_section_clusters：旋转滑动窗口。

    窗口扩展条件：同时满足 min_window_size 和 candidate_count >= target。
    """
    cluster_count = len(ordered_clusters)
    if cluster_count == 0:
        return []

    min_window_size = max(1, -(-cluster_count // max(1, section_count)))  # ceil division
    if section_count <= cluster_count:
        start = section_index * cluster_count // max(1, section_count)
    else:
        start = section_index % cluster_count

    selected: list[int] = []
    candidate_count = 0
    for offset in range(cluster_count):
        cluster = ordered_clusters[(start + offset) % cluster_count]
        if cluster not in selected:
            selected.append(cluster)
            candidate_count += cluster_counts.get(cluster, 0)
        if len(selected) >= min_window_size and candidate_count >= target:
            break
    return selected


def _build_paper_cluster_map(
    papers: list[dict],
    clusters: list[dict],
) -> tuple[dict[str, int], dict[int, list[str]]]:
    """
    构建论文-聚类映射。

    返回:
        paper_to_cluster: paper_id -> cluster_id
        cluster_to_papers: cluster_id -> [paper_id, ...]（保持 papers 中的顺序）
    """
    paper_to_cluster: dict[str, int] = {}
    cluster_to_papers: dict[int, list[str]] = {}

    for cluster in clusters:
        cluster_id: int = cluster["id"]
        cluster_to_papers[cluster_id] = []
        for pid in cluster.get("paper_ids", []):
            paper_to_cluster[pid] = cluster_id
            cluster_to_papers[cluster_id].append(pid)

    return paper_to_cluster, cluster_to_papers


def _get_ordered_clusters(papers: list[dict], paper_to_cluster: dict[str, int]) -> list[int]:
    """按论文出现顺序返回去重的聚类 ID 列表（对齐 Rust 版 ordered_input_clusters）"""
    seen: set[int] = set()
    ordered: list[int] = []
    for paper in papers:
        cid = paper_to_cluster.get(paper["id"])
        if cid is not None and cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered


def _get_cluster_counts(
    papers: list[dict],
    paper_to_cluster: dict[str, int],
    ordered_clusters: list[int],
) -> dict[int, int]:
    """对齐 Rust 版 cluster_counts：统计每个聚类的论文数"""
    known = set(ordered_clusters)
    counts: dict[int, int] = {}
    for paper in papers:
        cid = paper_to_cluster.get(paper["id"])
        if cid is not None and cid in known:
            counts[cid] = counts.get(cid, 0) + 1
    return counts


def _nearby_hybrid_candidates(
    anchor_indices: list[int],
    papers: list[dict],
    hybrid_edges: list[dict],
) -> list[NearbyHybridCandidate]:
    """
    对齐 Rust 版 nearby_hybrid_candidates：从混合图边中找跨聚类邻居。

    扫描所有 hybrid_edges，找到一端是锚点（社区内论文）、另一端不是的边，
    非锚点端成为候选。按权重降序排列。
    """
    if not anchor_indices or not hybrid_edges:
        return []

    paper_index = {p["id"]: i for i, p in enumerate(papers)}
    anchors = set(anchor_indices)
    candidates: dict[int, NearbyHybridCandidate] = {}

    for edge in hybrid_edges:
        src_id = edge.get("source_paper_id", "")
        tgt_id = edge.get("target_paper_id", "")
        src_idx = paper_index.get(src_id)
        tgt_idx = paper_index.get(tgt_id)
        if src_idx is None or tgt_idx is None:
            continue

        weight = edge.get("weight", 0.0)
        rank = edge.get("rank", 999)

        if src_idx in anchors and tgt_idx not in anchors:
            target_idx = tgt_idx
            anchor_idx = src_idx
        elif tgt_idx in anchors and src_idx not in anchors:
            target_idx = src_idx
            anchor_idx = tgt_idx
        else:
            continue

        existing = candidates.get(target_idx)
        if existing is None or weight > existing.weight or (
            weight == existing.weight and rank < existing.rank
        ):
            candidates[target_idx] = NearbyHybridCandidate(
                index=target_idx,
                anchor_index=anchor_idx,
                weight=weight,
                rank=rank,
            )

    result = sorted(candidates.values(), key=lambda c: (-c.weight, c.rank, c.anchor_index, c.index))
    return result


def plan_review_citations(
    sections: list[dict],
    papers: list[dict],
    clusters: list[dict],
    section_reference_target: int = 30,
    hybrid_edges: list[dict] | None = None,
    core_reference_count: int = 160,
) -> list[SectionCitationPlan]:
    """
    对齐 Rust 版 plan_review_citations：8 层优先级 + 混合图邻居。

    参数:
        sections: 大纲章节列表
        papers:   全部论文列表（已按 rerank 排序）
        clusters: 聚类数据列表
        section_reference_target: 每个章节的目标参考文献数量
        hybrid_edges: 混合图边列表（用于跨聚类邻居发现）
        core_reference_count: 核心论文数量（前 N 篇视为核心）
    """
    if not papers:
        return [
            SectionCitationPlan(
                section_index=i,
                section_title=sec.get("title", f"Section {i}"),
                key_clusters=sec.get("target_communities") or sec.get("key_clusters", []) or [],
                candidate_paper_ids=[],
                candidate_details=[],
            )
            for i, sec in enumerate(sections)
        ]

    paper_to_cluster, cluster_to_papers = _build_paper_cluster_map(papers, clusters)
    ordered_clusters = _get_ordered_clusters(papers, paper_to_cluster)
    cluster_cnts = _get_cluster_counts(papers, paper_to_cluster, ordered_clusters)
    section_count = len(sections)
    target = min(section_reference_target, len(papers))

    plans: list[SectionCitationPlan] = []
    for section_index, section in enumerate(sections):
        plan = _plan_section_citations(
            section_index=section_index,
            section_count=section_count,
            section=section,
            papers=papers,
            paper_to_cluster=paper_to_cluster,
            cluster_to_papers=cluster_to_papers,
            ordered_clusters=ordered_clusters,
            cluster_count=len(ordered_clusters),
            target=target,
            hybrid_edges=hybrid_edges or [],
            core_reference_count=core_reference_count,
            cluster_counts=cluster_cnts,
        )
        plans.append(plan)

    return plans


def _plan_section_citations(
    section_index: int,
    section_count: int,
    section: dict,
    papers: list[dict],
    paper_to_cluster: dict[str, int],
    cluster_to_papers: dict[int, list[str]],
    ordered_clusters: list[int],
    cluster_count: int,
    target: int,
    hybrid_edges: list[dict],
    core_reference_count: int,
    cluster_counts: dict[int, int],
) -> SectionCitationPlan:
    """
    对齐 Rust 版 plan_section_citations_with_context：8 层优先级系统。

    Tier 1: CommunityCore          - 主聚类核心论文
    Tier 2: CommunityAuxiliary     - 主聚类辅助论文
    Tier 3: HybridNeighborCore    - 混合图邻居核心论文（跨聚类桥接）
    Tier 4: HybridNeighborAuxiliary - 混合图邻居辅助论文
    Tier 5: RemainingCommunityCore - 剩余聚类核心论文（仅 Fallback 模式）
    Tier 6: RemainingCommunityAuxiliary - 剩余聚类辅助论文（仅 Fallback 模式）
    Tier 7: GlobalCore             - 全局核心论文（兜底）
    Tier 8: GlobalAuxiliary        - 全局辅助论文（兜底）
    """
    title = section.get("title", f"Section {section_index}")
    raw_key_clusters = section.get("target_communities") or section.get("key_clusters") or []
    core_end = min(core_reference_count, len(papers))

    # 确定主聚类集合（对齐 Rust 版 cluster_selection_for_section）
    fills_remaining = False
    if raw_key_clusters:
        primary_clusters = set(raw_key_clusters)
        key_clusters = list(raw_key_clusters)
    elif section_count <= 1 or cluster_count <= 1:
        primary_clusters = set(ordered_clusters)
        key_clusters = []
    else:
        fallback_ids = _fallback_section_clusters(
            section_index, section_count, target, ordered_clusters, cluster_counts
        )
        primary_clusters = {ordered_clusters[i] for i in fallback_ids if i < cluster_count}
        key_clusters = sorted(primary_clusters)
        fills_remaining = True

    # 收集主聚类论文索引（保持 papers 中的排序）
    community_indices: list[int] = []
    for i, paper in enumerate(papers):
        cid = paper_to_cluster.get(paper["id"])
        if cid is not None and cid in primary_clusters:
            community_indices.append(i)

    # 收集剩余聚类论文索引（仅 Fallback 模式）
    remaining_indices: list[int] = []
    if fills_remaining:
        for i, paper in enumerate(papers):
            cid = paper_to_cluster.get(paper["id"])
            if cid is not None and cid not in primary_clusters:
                remaining_indices.append(i)

    # 计算混合图邻居候选（对齐 Rust 版 nearby_hybrid_candidates）
    hybrid_candidates = _nearby_hybrid_candidates(community_indices, papers, hybrid_edges)

    # 按优先级选取（对齐 Rust 版 CandidateSelectionWriter）
    selected_ids: list[str] = []
    seen: set[str] = set()
    details: list[dict] = []

    def _push_idx(idx: int, source: CandidateSelectionSource) -> None:
        if len(selected_ids) >= target:
            return
        paper_id = papers[idx]["id"]
        if paper_id in seen:
            return
        seen.add(paper_id)
        selected_ids.append(paper_id)
        details.append({
            "paper_id": paper_id,
            "cluster_id": paper_to_cluster.get(paper_id),
            "is_core": idx < core_end,
            "source": source.value,
            "hybrid_anchor_paper_id": None,
            "hybrid_weight_basis_points": None,
        })

    def _push_hybrid(candidate: NearbyHybridCandidate, source: CandidateSelectionSource) -> None:
        if len(selected_ids) >= target:
            return
        paper_id = papers[candidate.index]["id"]
        if paper_id in seen:
            return
        seen.add(paper_id)
        selected_ids.append(paper_id)
        anchor_pid = papers[candidate.anchor_index]["id"] if candidate.anchor_index < len(papers) else None
        details.append({
            "paper_id": paper_id,
            "cluster_id": paper_to_cluster.get(paper_id),
            "is_core": candidate.index < core_end,
            "source": source.value,
            "hybrid_anchor_paper_id": anchor_pid,
            "hybrid_weight_basis_points": int(candidate.weight * 10000),
        })

    # Tier 1: CommunityCore
    for idx in community_indices:
        if idx < core_end:
            _push_idx(idx, CandidateSelectionSource.COMMUNITY_CORE)

    # Tier 2: CommunityAuxiliary
    for idx in community_indices:
        if idx >= core_end:
            _push_idx(idx, CandidateSelectionSource.COMMUNITY_AUXILIARY)

    # Tier 3: HybridNeighborCore
    for c in hybrid_candidates:
        if c.index < core_end:
            _push_hybrid(c, CandidateSelectionSource.HYBRID_NEIGHBOR_CORE)

    # Tier 4: HybridNeighborAuxiliary
    for c in hybrid_candidates:
        if c.index >= core_end:
            _push_hybrid(c, CandidateSelectionSource.HYBRID_NEIGHBOR_AUXILIARY)

    # Tier 5: RemainingCommunityCore（仅 Fallback 模式）
    if fills_remaining:
        for idx in remaining_indices:
            if idx < core_end:
                _push_idx(idx, CandidateSelectionSource.REMAINING_CORE)

    # Tier 6: RemainingCommunityAuxiliary（仅 Fallback 模式）
    if fills_remaining:
        for idx in remaining_indices:
            if idx >= core_end:
                _push_idx(idx, CandidateSelectionSource.REMAINING_AUXILIARY)

    # Tier 7: GlobalCore（兜底）
    for i in range(core_end):
        _push_idx(i, CandidateSelectionSource.GLOBAL_CORE)

    # Tier 8: GlobalAuxiliary（兜底）
    for i in range(core_end, len(papers)):
        _push_idx(i, CandidateSelectionSource.GLOBAL_AUXILIARY)

    return SectionCitationPlan(
        section_index=section_index,
        section_title=title,
        key_clusters=key_clusters,
        candidate_paper_ids=selected_ids,
        candidate_details=details,
    )


def render_section_references(
    plan: SectionCitationPlan,
    global_paper_map: dict[str, dict],
) -> str:
    """
    将章节的候选参考文献渲染为编号列表。

    参数:
        plan: 章节引用计划
        global_paper_map: paper_id -> 论文数据的全局映射

    返回:
        格式化的参考文献编号列表字符串
    """
    lines: list[str] = []
    for i, pid in enumerate(plan.candidate_paper_ids, 1):
        paper = global_paper_map.get(pid, {})
        authors = paper.get("authors", [])
        author_str = ", ".join(
            a.get("name", "Unknown") if isinstance(a, dict) else str(a)
            for a in authors[:3]
        )
        if len(authors) > 3:
            author_str += " et al."
        title = paper.get("title", "")
        venue = paper.get("journal", paper.get("venue", ""))
        year = paper.get("year", "")
        lines.append(f'[{i}] {author_str}, "{title}", {venue}, {year}.')
    return "\n".join(lines)


def citation_plan_summary(plans: list[SectionCitationPlan]) -> dict:
    """
    生成引用计划的统计摘要。

    返回:
        包含各章节和全局的候选来源计数统计字典
    """
    def _source_counts(details: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for d in details:
            src = d.get("source", "unknown")
            counts[src] = counts.get(src, 0) + 1
        return counts

    global_counts: dict[str, int] = {}
    sections_summary: list[dict] = []

    for plan in plans:
        section_counts = _source_counts(plan.candidate_details)
        for src, cnt in section_counts.items():
            global_counts[src] = global_counts.get(src, 0) + cnt
        sections_summary.append({
            "section_index": plan.section_index,
            "section_title": plan.section_title,
            "key_clusters": plan.key_clusters,
            "candidate_reference_count": len(plan.candidate_paper_ids),
            "primary_reference_count": len(plan.primary_paper_ids),
            "secondary_reference_count": len(plan.secondary_paper_ids),
            "candidate_source_counts": section_counts,
        })

    return {
        "section_count": len(plans),
        "sections": sections_summary,
        "candidate_source_counts": global_counts,
    }
