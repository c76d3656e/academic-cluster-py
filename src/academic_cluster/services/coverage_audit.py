"""
Coverage audit - deterministic check that the review covers planned citations.

Aligned with Rust version citation_coverage.rs and routing.rs.

Measures:
- Cluster coverage: fraction of eligible clusters that have at least one cited paper
- Candidate coverage: fraction of planned candidates that were actually cited
- Assembly retention: fraction of draft references retained in final assembly
- Core vs auxiliary citation counts
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Quality thresholds (basis points, 10000 = 100%)
MIN_WEIGHTED_COVERAGE_BP: int = 8000  # 80%
MIN_ASSEMBLY_RETENTION_BP: int = 9000  # 90%


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ClusterCoverageDetail:
    """Per-cluster coverage info (mirrors Rust ClusterCoverage)."""

    cluster_id: str
    eligible: bool
    covered: bool
    candidate_count: int = 0
    cited_candidate_count: int = 0
    uncovered_candidate_count: int = 0
    coverage_ratio_bp: int = 0


@dataclass
class SectionCoverageDetail:
    """Per-section coverage info (mirrors Rust SectionCoverage)."""

    section_index: int
    section_title: str
    key_clusters: list[int] = field(default_factory=list)
    candidate_count: int = 0
    cited_candidate_count: int = 0
    uncovered_candidate_count: int = 0
    coverage_ratio_bp: int = 0


@dataclass
class CoverageAuditReport:
    """Full coverage audit result (mirrors Rust CitationCoverageReport)."""

    # High-level metrics (basis points)
    cluster_coverage_bp: int = 0
    candidate_coverage_bp: int = 0
    weighted_coverage_bp: int = 0
    assembly_retention_bp: int = 0

    # Counts
    cited_core_count: int = 0
    cited_auxiliary_count: int = 0
    total_candidates: int = 0
    total_cited: int = 0
    planned_candidate_count: int = 0
    cited_candidate_count: int = 0
    cited_unplanned_count: int = 0
    draft_unique_reference_count: int = 0
    assembled_unique_reference_count: int = 0
    dropped_citation_count: int = 0

    # Diagnostics
    orphan_clusters: list[str] = field(default_factory=list)
    uncovered_candidates: list[str] = field(default_factory=list)
    cited_unplanned_paper_ids: list[str] = field(default_factory=list)

    # Detail breakdowns
    sections: list[SectionCoverageDetail] = field(default_factory=list)
    clusters: list[ClusterCoverageDetail] = field(default_factory=list)

    # Gate result
    passes: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for JSON compatibility."""
        return {
            "cluster_coverage_bp": self.cluster_coverage_bp,
            "candidate_coverage_bp": self.candidate_coverage_bp,
            "weighted_coverage_bp": self.weighted_coverage_bp,
            "assembly_retention_bp": self.assembly_retention_bp,
            "cited_core_count": self.cited_core_count,
            "cited_auxiliary_count": self.cited_auxiliary_count,
            "total_candidates": self.total_candidates,
            "total_cited": self.total_cited,
            "planned_candidate_count": self.planned_candidate_count,
            "cited_candidate_count": self.cited_candidate_count,
            "cited_unplanned_count": self.cited_unplanned_count,
            "draft_unique_reference_count": self.draft_unique_reference_count,
            "assembled_unique_reference_count": self.assembled_unique_reference_count,
            "dropped_citation_count": self.dropped_citation_count,
            "orphan_clusters": self.orphan_clusters,
            "uncovered_candidates": self.uncovered_candidates,
            "cited_unplanned_paper_ids": self.cited_unplanned_paper_ids,
            "sections": [
                {
                    "section_index": s.section_index,
                    "section_title": s.section_title,
                    "key_clusters": s.key_clusters,
                    "candidate_count": s.candidate_count,
                    "cited_candidate_count": s.cited_candidate_count,
                    "uncovered_candidate_count": s.uncovered_candidate_count,
                    "coverage_ratio_bp": s.coverage_ratio_bp,
                }
                for s in self.sections
            ],
            "clusters": [
                {
                    "cluster_id": c.cluster_id,
                    "eligible": c.eligible,
                    "covered": c.covered,
                    "candidate_count": c.candidate_count,
                    "cited_candidate_count": c.cited_candidate_count,
                    "uncovered_candidate_count": c.uncovered_candidate_count,
                    "coverage_ratio_bp": c.coverage_ratio_bp,
                }
                for c in self.clusters
            ],
            "pass": self.passes,
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ratio_bp(numerator: int, denominator: int) -> int:
    """Compute a ratio in basis points (10000 = 100%). Returns 0 when denominator is 0."""
    if denominator == 0:
        return 0
    return (numerator * 10_000) // denominator


# ---------------------------------------------------------------------------
# Core audit function
# ---------------------------------------------------------------------------


def audit_citation_coverage(
    *,
    section_citations: list[set[int]],
    candidate_plans: list[list[str]],
    cluster_paper_map: dict[str, list[str]],
    cited_paper_ids: set[str],
    candidate_paper_ids: list[str],
    core_paper_ids: set[str],
    section_titles: list[str] | None = None,
    section_key_clusters: list[list[int]] | None = None,
    draft_reference_numbers: set[int] | None = None,
    assembled_reference_numbers: set[int] | None = None,
) -> CoverageAuditReport:
    """
    Audit citation coverage across clusters and candidates.

    Parameters
    ----------
    section_citations : list[set[int]]
        Per-section sets of cited reference numbers (1-based).
    candidate_plans : list[list[str]]
        Per-section candidate paper_id lists.
    cluster_paper_map : dict[str, list[str]]
        Mapping from cluster_id to list of paper_ids in that cluster.
    cited_paper_ids : set[str]
        Set of paper_ids that were actually cited in the final review.
    candidate_paper_ids : list[str]
        All candidate paper_ids (ordered, 1-based index = reference number).
    core_paper_ids : set[str]
        Set of paper_ids that are "core" references.
    section_titles : list[str] | None
        Optional per-section titles for diagnostics.
    section_key_clusters : list[list[int]] | None
        Optional per-section key cluster lists for diagnostics.
    draft_reference_numbers : set[int] | None
        Reference numbers present in draft section bodies. Used to compute
        assembly retention. If None, retention defaults to 10000 (perfect).
    assembled_reference_numbers : set[int] | None
        Reference numbers present in final assembled markdown. Used together
        with draft_reference_numbers to compute assembly retention.

    Returns
    -------
    CoverageAuditReport
    """
    candidate_set = set(candidate_paper_ids)
    cited_candidates = candidate_set & cited_paper_ids
    uncovered_candidates = sorted(candidate_set - cited_paper_ids)
    cited_unplanned = sorted(cited_paper_ids - candidate_set)

    # -- Cluster coverage --
    total_clusters = len(cluster_paper_map)
    covered_clusters = 0
    orphan_clusters: list[str] = []
    cluster_details: list[ClusterCoverageDetail] = []

    for cid, papers in cluster_paper_map.items():
        cluster_paper_set = set(papers)
        # Candidates belonging to this cluster
        cluster_candidates = cluster_paper_set & candidate_set
        cluster_cited_candidates = cluster_candidates & cited_paper_ids
        is_covered = bool(cluster_paper_set & cited_paper_ids)
        if is_covered:
            covered_clusters += 1
        else:
            orphan_clusters.append(cid)
        cluster_details.append(
            ClusterCoverageDetail(
                cluster_id=cid,
                eligible=True,  # all clusters in the map are eligible
                covered=is_covered,
                candidate_count=len(cluster_candidates),
                cited_candidate_count=len(cluster_cited_candidates),
                uncovered_candidate_count=len(cluster_candidates - cited_paper_ids),
                coverage_ratio_bp=_ratio_bp(
                    len(cluster_cited_candidates), len(cluster_candidates)
                ),
            )
        )

    cluster_coverage_bp = (
        _ratio_bp(covered_clusters, total_clusters) if total_clusters > 0 else 10_000
    )

    # -- Candidate coverage --
    total_candidates = len(candidate_set)
    candidate_coverage_bp = (
        _ratio_bp(len(cited_candidates), total_candidates)
        if total_candidates > 0
        else 10_000
    )

    # -- Core vs auxiliary --
    cited_core = cited_paper_ids & core_paper_ids
    cited_auxiliary = cited_paper_ids - core_paper_ids

    # -- Assembly retention --
    if draft_reference_numbers is not None and assembled_reference_numbers is not None:
        if len(draft_reference_numbers) > 0:
            retained = len(assembled_reference_numbers & draft_reference_numbers)
            assembly_retention_bp = _ratio_bp(retained, len(draft_reference_numbers))
        else:
            assembly_retention_bp = 10_000
        draft_unique_count = len(draft_reference_numbers)
        assembled_unique_count = len(assembled_reference_numbers)
        dropped_count = len(draft_reference_numbers - assembled_reference_numbers)
    else:
        # No draft/final data available: assume perfect retention
        assembly_retention_bp = 10_000
        draft_unique_count = 0
        assembled_unique_count = 0
        dropped_count = 0

    # -- Weighted coverage (combination of cluster + candidate coverage) --
    # Matches Rust: importance-weighted eligible cluster coverage.
    # Python approximation: 60% cluster + 40% candidate.
    weighted_coverage_bp = round(
        cluster_coverage_bp * 0.6 + candidate_coverage_bp * 0.4
    )

    # -- Section-level detail --
    section_details: list[SectionCoverageDetail] = []
    num_sections = max(len(section_citations), len(candidate_plans))
    for i in range(num_sections):
        title = (
            section_titles[i]
            if section_titles and i < len(section_titles)
            else f"Section {i}"
        )
        key_cls = (
            section_key_clusters[i]
            if section_key_clusters and i < len(section_key_clusters)
            else []
        )
        plan_set = set(candidate_plans[i]) if i < len(candidate_plans) else set()
        cited_in_section = plan_set & cited_paper_ids
        section_details.append(
            SectionCoverageDetail(
                section_index=i,
                section_title=title,
                key_clusters=key_cls,
                candidate_count=len(plan_set),
                cited_candidate_count=len(cited_in_section),
                uncovered_candidate_count=len(plan_set - cited_paper_ids),
                coverage_ratio_bp=_ratio_bp(len(cited_in_section), len(plan_set)),
            )
        )

    # -- Pass/fail gate --
    passes = (
        weighted_coverage_bp >= MIN_WEIGHTED_COVERAGE_BP
        and assembly_retention_bp >= MIN_ASSEMBLY_RETENTION_BP
    )

    return CoverageAuditReport(
        cluster_coverage_bp=cluster_coverage_bp,
        candidate_coverage_bp=candidate_coverage_bp,
        weighted_coverage_bp=weighted_coverage_bp,
        assembly_retention_bp=assembly_retention_bp,
        cited_core_count=len(cited_core),
        cited_auxiliary_count=len(cited_auxiliary),
        total_candidates=total_candidates,
        total_cited=len(cited_paper_ids),
        planned_candidate_count=total_candidates,
        cited_candidate_count=len(cited_candidates),
        cited_unplanned_count=len(cited_unplanned),
        draft_unique_reference_count=draft_unique_count,
        assembled_unique_reference_count=assembled_unique_count,
        dropped_citation_count=dropped_count,
        orphan_clusters=sorted(orphan_clusters),
        uncovered_candidates=uncovered_candidates[:20],
        cited_unplanned_paper_ids=cited_unplanned[:20],
        sections=section_details,
        clusters=cluster_details,
        passes=passes,
    )


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------

CoverageAuditRoute = Literal["pass", "repair", "refine", "fail"]


def route_after_coverage_audit(
    coverage_result: CoverageAuditReport | dict[str, Any],
    invalid_citation_count: int,
    revision_attempts_remaining: int,
    missing_evidence_card_count: int = 0,
) -> CoverageAuditRoute:
    """
    Route based on coverage audit results.

    Aligned with Rust routing.rs route_after_coverage_audit().

    Routing logic:
    - pass:   invalid == 0 AND missing_evidence == 0 AND weighted_coverage >= 80%
              AND assembly_retention >= 90%
    - repair: invalid > 0 and revision attempts remain
    - refine: no invalid citations but coverage/retention below threshold
              (or missing evidence cards), and attempts remain
    - fail:   terminal failure after retries

    Parameters
    ----------
    coverage_result : CoverageAuditReport | dict
        Result from audit_citation_coverage(). Accepts either the dataclass
        or a plain dict (for backward compatibility).
    invalid_citation_count : int
        Number of invalid citations found.
    revision_attempts_remaining : int
        How many revision attempts are left.
    missing_evidence_card_count : int
        Number of missing evidence cards (default 0).

    Returns
    -------
    str
        One of: "pass", "repair", "refine", "fail"
    """
    # Extract values from either dataclass or dict
    if isinstance(coverage_result, CoverageAuditReport):
        passes = coverage_result.passes
    else:
        passes = coverage_result.get("pass", False)

    # All-clear: no invalid citations, no missing evidence, thresholds met
    if invalid_citation_count == 0 and missing_evidence_card_count == 0 and passes:
        return "pass"

    # Invalid citations with attempts remaining: repair
    if invalid_citation_count > 0 and revision_attempts_remaining > 0:
        return "repair"

    # No invalid citations but coverage below threshold or missing evidence:
    # targeted refinement
    if invalid_citation_count == 0 and revision_attempts_remaining > 0:
        return "refine"

    # Terminal failure
    return "fail"
