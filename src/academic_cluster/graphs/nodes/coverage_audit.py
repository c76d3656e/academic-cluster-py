"""
覆盖审计节点 - 评估综述的引用覆盖率
"""

import re

import structlog

from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def coverage_audit_node(state: PipelineState) -> dict:
    """
    覆盖审计

    评估综述的引用覆盖率：
    - 计算每个社区的引用覆盖率
    - 检查无效引用（引用了不存在的论文）
    - 计算组装保留率
    - 决定是否需要修订
    """
    logger.info("Starting coverage audit")

    db = get_database()

    try:
        # 获取已写章节
        written_sections = []
        for section_id in state.written_section_ids:
            # TODO: 从数据库获取章节内容
            pass

        # 获取有效论文 ID
        valid_paper_ids = set(state.core_paper_ids + state.auxiliary_paper_ids)

        # 统计引用
        total_citations = 0
        invalid_citations = 0

        for section in written_sections:
            content = section.get("content", "")
            # 提取引用标记 [N]
            citations = re.findall(r'\[(\d+)\]', content)
            total_citations += len(citations)

            # 检查引用有效性（简化版本）
            for cite in citations:
                # TODO: 实际应该检查引用映射
                pass

        # 计算覆盖率
        if total_citations > 0:
            coverage_score = 1.0 - (invalid_citations / total_citations)
        else:
            coverage_score = 0.0

        needs_revision = coverage_score < 0.8 or invalid_citations > 0

        logger.info(
            "Coverage audit completed",
            coverage=coverage_score,
            total_citations=total_citations,
            invalid_citations=invalid_citations,
            needs_revision=needs_revision,
        )

        return {
            "coverage_score": coverage_score,
            "invalid_citation_count": invalid_citations,
            "status": "audited",
        }

    except Exception as e:
        logger.error("Coverage audit failed", error=str(e))
        return {
            "coverage_score": 0.0,
            "invalid_citation_count": 0,
            "status": "audited",
            "errors": [f"Coverage audit failed: {str(e)}"],
        }
