"""
Citation Planner - 为综述论文各章节分配候选参考文献

基于 Rust 版 Prism 的 8 层优先级系统简化而来：
1. CommunityCore      - 主聚类中的核心文献
2. CommunityAuxiliary  - 主聚类中的辅助文献
3. RemainingCore      - 剩余聚类中的核心文献
4. RemainingAuxiliary  - 剩余聚类中的辅助文献
5. GlobalCore          - 全局核心文献（兜底）
6. GlobalAuxiliary     - 全局辅助文献（兜底）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class CandidateSelectionSource(str, Enum):
    """候选文献的选取来源（优先级从高到低）"""
    COMMUNITY_CORE = "community_core"
    COMMUNITY_AUXILIARY = "community_auxiliary"
    REMAINING_CORE = "remaining_core"
    REMAINING_AUXILIARY = "remaining_auxiliary"
    GLOBAL_CORE = "global_core"
    GLOBAL_AUXILIARY = "global_auxiliary"


@dataclass
class SectionCitationCandidate:
    """单篇候选文献的详细信息"""
    paper_id: str
    cluster_id: int | None
    is_core: bool
    source: CandidateSelectionSource


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
    cluster_count: int,
) -> list[int]:
    """
    当章节没有指定 key_clusters 时，使用滑动窗口将聚类分配给各章节。

    确保每个聚类至少被一个章节覆盖，且相邻章节的聚类集合有适度重叠。
    """
    if cluster_count == 0:
        return []
    window_size = max(1, (cluster_count + section_count - 1) // section_count)
    start = section_index * cluster_count // max(1, section_count)
    selected: list[int] = []
    for offset in range(cluster_count):
        idx = (start + offset) % cluster_count
        if idx not in selected:
            selected.append(idx)
        if len(selected) >= window_size:
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

    # 从 clusters 列表构建 cluster -> paper_ids 映射
    for cluster in clusters:
        cluster_id: int = cluster["id"]
        cluster_to_papers[cluster_id] = []
        for pid in cluster.get("paper_ids", []):
            paper_to_cluster[pid] = cluster_id
            cluster_to_papers[cluster_id].append(pid)

    return paper_to_cluster, cluster_to_papers


def _get_ordered_clusters(papers: list[dict], paper_to_cluster: dict[str, int]) -> list[int]:
    """按论文出现顺序返回去重的聚类 ID 列表"""
    seen: set[int] = set()
    ordered: list[int] = []
    for paper in papers:
        cid = paper_to_cluster.get(paper["id"])
        if cid is not None and cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered


def plan_review_citations(
    sections: list[dict],
    papers: list[dict],
    clusters: list[dict],
    section_reference_target: int = 30,
) -> list[SectionCitationPlan]:
    """
    为综述论文的每个章节规划候选参考文献。

    参数:
        sections: 大纲章节列表，每个章节可包含 "key_clusters" (list[int]) 和 "title" 字段
        papers:   核心论文列表（已按 rerank 排序），每篇需有 "id" 字段，
                  前 core_reference_count 篇视为核心文献
        clusters: 聚类数据列表，每个需有 "id" (int) 和 "paper_ids" (list[str]) 字段
        section_reference_target: 每个章节的目标参考文献数量上限

    返回:
        SectionCitationPlan 列表，每个章节一个
    """
    if not papers:
        return [
            SectionCitationPlan(
                section_index=i,
                section_title=sec.get("title", f"Section {i}"),
                key_clusters=sec.get("key_clusters", []) or [],
                candidate_paper_ids=[],
                candidate_details=[],
            )
            for i, sec in enumerate(sections)
        ]

    paper_to_cluster, cluster_to_papers = _build_paper_cluster_map(papers, clusters)
    ordered_clusters = _get_ordered_clusters(papers, paper_to_cluster)
    section_count = len(sections)
    cluster_count = len(ordered_clusters)
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
            cluster_count=cluster_count,
            target=target,
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
) -> SectionCitationPlan:
    """为单个章节规划候选参考文献"""
    title = section.get("title", f"Section {section_index}")
    raw_key_clusters = section.get("key_clusters") or []

    # 确定主聚类集合
    if raw_key_clusters:
        primary_clusters = set(raw_key_clusters)
        key_clusters = list(raw_key_clusters)
    elif section_count <= 1 or cluster_count <= 1:
        # 单章节或单聚类 => 覆盖全部
        primary_clusters = set(ordered_clusters)
        key_clusters = []
    else:
        # 滑动窗口 fallback
        fallback_ids = _fallback_section_clusters(section_index, section_count, cluster_count)
        primary_clusters = {ordered_clusters[i] for i in fallback_ids if i < cluster_count}
        key_clusters = sorted(primary_clusters)

    # 收集主聚类论文（保持 papers 中的排序）
    community_paper_ids: list[str] = []
    for paper in papers:
        cid = paper_to_cluster.get(paper["id"])
        if cid is not None and cid in primary_clusters:
            community_paper_ids.append(paper["id"])

    # 收集剩余聚类论文
    remaining_paper_ids: list[str] = []
    if not raw_key_clusters and cluster_count > 1:
        # 仅在 fallback 模式下才填充剩余聚类
        for paper in papers:
            cid = paper_to_cluster.get(paper["id"])
            if cid is not None and cid not in primary_clusters:
                remaining_paper_ids.append(paper["id"])

    # 按优先级选取
    selected_ids: list[str] = []
    seen: set[str] = set()
    details: list[dict] = []

    def _push(paper_id: str, source: CandidateSelectionSource, is_core: bool) -> None:
        if len(selected_ids) >= target:
            return
        if paper_id in seen:
            return
        seen.add(paper_id)
        selected_ids.append(paper_id)
        details.append({
            "paper_id": paper_id,
            "cluster_id": paper_to_cluster.get(paper_id),
            "is_core": is_core,
            "source": source.value,
        })

    # Tier 1-2: 主聚类论文
    for pid in community_paper_ids:
        _push(pid, CandidateSelectionSource.COMMUNITY_CORE, True)
    for pid in community_paper_ids:
        _push(pid, CandidateSelectionSource.COMMUNITY_AUXILIARY, False)

    # Tier 3-4: 剩余聚类论文
    for pid in remaining_paper_ids:
        _push(pid, CandidateSelectionSource.REMAINING_CORE, True)
    for pid in remaining_paper_ids:
        _push(pid, CandidateSelectionSource.REMAINING_AUXILIARY, False)

    # Tier 5-6: 全局兜底
    for pid in (p["id"] for p in papers):
        _push(pid, CandidateSelectionSource.GLOBAL_CORE, True)
    for pid in (p["id"] for p in papers):
        _push(pid, CandidateSelectionSource.GLOBAL_AUXILIARY, False)

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
