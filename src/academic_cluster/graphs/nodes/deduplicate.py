"""
去重节点 - 去除重复论文

对齐 Rust 版 academic-cluster-rs 的 dedup.rs 实现：
1. 优先使用 DOI 去重（标准化后比较，不同格式的同一 DOI 能被识别）
2. DOI 不存在时回退到标题去重（归一化后比较）
3. 短标题（<10字符）使用 source:external_id 作为兜底 key
"""

import structlog

from ...services.database import get_database
from ...tools.doi import is_valid_doi, normalize_doi
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()


def _normalize_title_for_dedup(title: str) -> str:
    """
    标准化标题用于去重（对齐 Rust 版 normalize_title_for_dedup）。

    - 转小写
    - 只保留字母数字和 CJK 字符
    """
    import unicodedata

    title = title.strip().lower()
    return "".join(
        ch for ch in title if ch.isalnum() or unicodedata.category(ch).startswith("Lo")
    )


def _make_dedup_key(paper: dict) -> str:
    """
    为论文生成去重 key（对齐 Rust 版 dedup_candidates 逻辑）。

    优先级：
    1. DOI（标准化后）
    2. 归一化标题（长度 >= 10）
    3. source:external_id（短标题兜底）
    """
    # 1. 尝试 DOI
    doi = paper.get("doi")
    if not doi:
        # 从 external_id 提取
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

    # 3. 兜底: source + external_id
    source = paper.get("source", "unknown")
    ext_id = paper.get("external_id", paper.get("id", ""))
    return f"source:{source}:{ext_id}"


async def deduplicate_node(state: PipelineState) -> dict:
    """
    去除重复论文

    对齐 Rust 版 dedup_candidates 逻辑：
    - DOI 优先去重（标准化后比较，支持不同格式的同一 DOI）
    - 标题归一化去重
    - 短标题使用 source identity 兜底
    """
    logger.info("Starting deduplication", paper_count=len(state.paper_ids))

    db = get_database()
    papers = await db.get_papers_by_ids(state.paper_ids)

    # 使用 set 去重（对齐 Rust 版 BTreeSet::insert）
    seen_keys: set[str] = set()
    final_papers = []

    for paper in papers:
        key = _make_dedup_key(paper)
        if key not in seen_keys:
            seen_keys.add(key)
            final_papers.append(paper)

    deduplicated_ids = [p.get("id") for p in final_papers]

    logger.info(
        "Deduplication completed",
        original_count=len(state.paper_ids),
        deduplicated_count=len(deduplicated_ids),
        removed=len(state.paper_ids) - len(deduplicated_ids),
    )

    await send_progress(
        state.project_id,
        "deduplicate",
        f"去重完成，保留 {len(deduplicated_ids)} 篇",
        detail={"removed": len(state.paper_ids) - len(deduplicated_ids)},
    )

    return {
        "paper_ids": deduplicated_ids,
        "status": "deduplicated",
    }
