"""
覆盖审计节点 - 评估综述的引用覆盖率

对齐 Rust 版 citation_coverage.rs：
- 使用 citation_utils.validate_citations 进行引用校验
- 聚类级覆盖率追踪
- 加权覆盖率（basis points）
- 弱引用支撑检测
"""

import contextlib
import re
import traceback

import structlog

from ...services.citation_utils import validate_citations
from ...services.database import get_database
from ...services.observability import get_current_tracker
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()

# 对齐 Rust 版 MIN_WEIGHTED_COVERAGE_BASIS_POINTS
_MIN_WEIGHTED_COVERAGE_BP = 8000  # 80%


def _extract_cited_indices(text: str) -> set[int]:
    """从文本中提取所有被引用的 [N] 编号"""
    cited = set()
    for match in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", text):
        for num_str in match.group(1).split(","):
            with contextlib.suppress(ValueError):
                cited.add(int(num_str.strip()))
    return cited


def _compute_cluster_coverage(
    written_sections: list[dict],
    clusters: list[dict],
    core_paper_ids: list[str],
    auxiliary_paper_ids: list[str],
) -> dict:
    """
    计算聚类级覆盖率（对齐 Rust 版 citation_coverage.rs）。

    检查每个聚类是否在综述中被引用覆盖。
    """
    # 构建 paper_id -> cluster_id 映射
    paper_to_cluster: dict[str, int] = {}
    for cluster in clusters:
        cid = cluster.get("id")
        for pid in cluster.get("paper_ids", []):
            paper_to_cluster[pid] = cid

    # 构建 citation_number -> paper_id 映射
    all_paper_ids = core_paper_ids + auxiliary_paper_ids
    num_to_paper: dict[int, str] = {}
    for i, pid in enumerate(all_paper_ids):
        num_to_paper[i + 1] = pid

    # 从所有章节中提取被引用的编号
    all_cited_indices = set()
    for section in written_sections:
        content = section.get("content", "")
        all_cited_indices.update(_extract_cited_indices(content))

    # 转换为 paper_ids
    cited_paper_ids = set()
    for idx in all_cited_indices:
        pid = num_to_paper.get(idx)
        if pid:
            cited_paper_ids.add(pid)

    # 计算每个聚类的覆盖情况
    eligible_clusters = 0
    covered_clusters = 0
    orphan_cluster_ids = []
    cluster_details = []

    for cluster in clusters:
        cid = cluster.get("id")
        cluster_paper_ids = set(cluster.get("paper_ids", []))
        if not cluster_paper_ids:
            continue

        eligible_clusters += 1
        covered = cluster_paper_ids & cited_paper_ids
        if covered:
            covered_clusters += 1
        else:
            orphan_cluster_ids.append(cid)

        cluster_details.append({
            "cluster_id": cid,
            "paper_count": len(cluster_paper_ids),
            "cited_count": len(covered),
            "coverage": len(covered) / max(len(cluster_paper_ids), 1),
        })

    equal_weight_bp = (covered_clusters * 10000) // max(eligible_clusters, 1)

    return {
        "eligible_cluster_count": eligible_clusters,
        "covered_cluster_count": covered_clusters,
        "orphan_cluster_ids": orphan_cluster_ids,
        "equal_weight_coverage_bp": equal_weight_bp,
        "cluster_details": cluster_details,
    }


def _detect_weak_citation_support(
    written_sections: list[dict],
    valid_paper_count: int,
) -> int:
    """
    检测弱引用支撑（对齐 Rust 版 citation_support.rs）。

    检查每个包含事实判断的句子是否有 [N] 引用支撑。
    返回缺乏引用支撑的句子数。
    """
    weak_count = 0
    # 匹配包含事实判断关键词的句子
    fact_patterns = re.compile(
        r"(?:表明|发现|证明|提出|显示|实现了|达到了|优于|优于|outperform|achieve|demonstrate|show|propose|present)"
        r".*?(?:。|$)",
        re.IGNORECASE,
    )
    citation_pattern = re.compile(r"\[\d+(?:\s*,\s*\d+)*\]")

    for section in written_sections:
        content = section.get("content", "")
        sentences = re.split(r"[。！？；\n]", content)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence or len(sentence) < 15:
                continue
            # 如果句子包含事实判断但没有引用
            if fact_patterns.search(sentence) and not citation_pattern.search(sentence):
                weak_count += 1

    return weak_count


async def coverage_audit_node(state: PipelineState) -> dict:
    """
    覆盖审计（对齐 Rust 版 citation_coverage.rs）

    评估综述的引用覆盖率：
    - 检查无效引用（引用了不存在的论文）
    - 计算聚类级覆盖率
    - 加权覆盖率（basis points）
    - 弱引用支撑检测
    - 决定是否需要修订
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("coverage_audit", "compute", index=8)

    logger.info("Starting coverage audit")

    await send_progress(
        state.project_id, "coverage_audit",
        "覆盖率审计中...",
    )

    db = get_database()

    try:
        # 获取已写章节
        written_sections = await db.get_written_sections_by_ids(state.written_section_ids)
        if not written_sections:
            raise ValueError("No written sections to audit - write_review must complete first")

        valid_paper_count = len(state.core_paper_ids)
        total_papers = valid_paper_count + len(state.auxiliary_paper_ids)

        # === 1. 引用有效性校验 ===
        total_citations = 0
        total_valid = 0
        total_invalid = 0

        for section in written_sections:
            content = section.get("content", "")
            result = validate_citations(content, valid_paper_count)
            total_valid += result["valid_count"]
            total_invalid += result["invalid_count"]
            total_citations += result["valid_count"] + result["invalid_count"]

        # 引用覆盖率
        citation_coverage = total_valid / max(total_citations, 1)

        # === 2. 论文覆盖率 ===
        final_review = state.final_review or ""
        all_cited_indices = set()
        if final_review:
            all_cited_indices = _extract_cited_indices(final_review)
        paper_coverage = len(all_cited_indices) / max(total_papers, 1)

        # === 3. 聚类级覆盖率 ===
        clusters = await db.get_clusters_by_ids(state.cluster_ids)
        cluster_cov = _compute_cluster_coverage(
            written_sections, clusters,
            state.core_paper_ids, state.auxiliary_paper_ids,
        )

        # === 4. 弱引用支撑检测 ===
        weak_support_count = _detect_weak_citation_support(
            written_sections, valid_paper_count,
        )

        # === 5. 综合判断 ===
        weighted_bp = cluster_cov["equal_weight_coverage_bp"]
        needs_revision = (
            total_invalid > 0
            or weighted_bp < _MIN_WEIGHTED_COVERAGE_BP
            or weak_support_count > 5
        )

        logger.info(
            "Coverage audit completed",
            citation_coverage=citation_coverage,
            paper_coverage=paper_coverage,
            weighted_coverage_bp=weighted_bp,
            total_citations=total_citations,
            invalid_citations=total_invalid,
            cited_papers=len(all_cited_indices),
            total_papers=total_papers,
            orphan_clusters=len(cluster_cov["orphan_cluster_ids"]),
            weak_support_count=weak_support_count,
            needs_revision=needs_revision,
        )

        await send_progress(
            state.project_id, "coverage_audit",
            f"覆盖率审计完成：引用 {citation_coverage:.0%}，聚类 {weighted_bp/100:.0f}%，"
            f"无效 {total_invalid}，弱支撑 {weak_support_count}",
            detail={
                "citation_coverage": citation_coverage,
                "paper_coverage": paper_coverage,
                "weighted_coverage_bp": weighted_bp,
                "invalid_citations": total_invalid,
                "weak_support_count": weak_support_count,
                "orphan_clusters": len(cluster_cov["orphan_cluster_ids"]),
                "needs_revision": needs_revision,
            },
        )

        result = {
            "coverage_score": citation_coverage,
            "weighted_coverage_bp": weighted_bp,
            "invalid_citation_count": total_invalid,
            "weak_citation_support_count": weak_support_count,
            "orphan_cluster_count": len(cluster_cov["orphan_cluster_ids"]),
            "status": "audited",
        }
        if tracker:
            await tracker.end_node("coverage_audit", "succeeded", output_summary={
                "coverage_score": citation_coverage,
                "weighted_coverage_bp": weighted_bp,
                "invalid_citations": total_invalid,
            })
        return result

    except Exception as e:
        if tracker:
            await tracker.end_node("coverage_audit", "failed",
                                   error_message=str(e),
                                   error_traceback=traceback.format_exc())
        logger.error("Coverage audit failed", error=str(e))
        raise
