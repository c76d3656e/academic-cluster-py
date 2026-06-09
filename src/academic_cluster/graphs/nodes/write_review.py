"""
综述写作节点 - 生成综述内容
"""

import asyncio

import structlog

from ..state import PipelineState

logger = structlog.get_logger()


async def write_review_node(state: PipelineState) -> dict:
    """
    写作综述

    使用 LLM 生成综述内容：
    1. 生成章节计划（每个章节的关键点和引用）
    2. 生成引用计划（每个章节使用哪些论文）
    3. 并行写入各章节
    4. 组装综述
    5. 生成 BibTeX
    """
    logger.info("Starting review writing", outline_id=state.outline_id)

    # TODO: 实现综述写作
    # 1. 从数据库获取大纲
    # 2. 生成章节计划
    # 3. 生成引用计划
    # 4. 并行写入各章节（使用 Agent）
    # 5. 组装综述
    # 6. 生成 BibTeX
    # 7. 存储到数据库

    section_plan_ids = []
    citation_plan_ids = []
    written_section_ids = []
    final_review_id = None
    bibtex = None

    logger.info("Review writing completed")

    return {
        "section_plan_ids": section_plan_ids,
        "citation_plan_ids": citation_plan_ids,
        "written_section_ids": written_section_ids,
        "final_review_id": final_review_id,
        "bibtex": bibtex,
        "status": "written",
    }
