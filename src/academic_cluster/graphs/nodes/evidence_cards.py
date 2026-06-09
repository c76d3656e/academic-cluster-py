"""
证据卡片节点 - 为论文生成结构化证据卡片
"""

import asyncio

import structlog

from ...agents.evidence_generation import generate_evidence_cards_batch
from ...services.database import get_database
from ..state import PipelineState

logger = structlog.get_logger()


async def evidence_cards_node(state: PipelineState) -> dict:
    """
    生成证据卡片

    使用 LLM 为每篇核心论文生成结构化证据卡片：
    - paper_id: 论文 ID
    - title: 标题
    - claim: 核心主张
    - evidence_span: 证据片段
    - method: 使用的方法
    - metric: 评估指标
    - limitation: 局限性
    - confidence: 置信度
    """
    logger.info("Starting evidence card generation", core_papers=len(state.core_paper_ids))

    db = get_database()

    # 获取核心论文详情
    papers = await db.get_papers_by_ids(state.core_paper_ids)

    if not papers:
        logger.warning("No papers for evidence generation")
        return {
            "evidence_card_ids": [],
            "status": "evidence_generated",
        }

    try:
        # 批量生成证据卡片
        evidence_cards = await generate_evidence_cards_batch(papers)

        # 保存到数据库
        evidence_card_ids = []
        for card in evidence_cards:
            card_id = await db.save_evidence_card(card)
            evidence_card_ids.append(card_id)

        logger.info(
            "Evidence card generation completed",
            cards=len(evidence_card_ids),
        )

        return {
            "evidence_card_ids": evidence_card_ids,
            "status": "evidence_generated",
        }

    except Exception as e:
        logger.error("Evidence generation failed", error=str(e))
        return {
            "evidence_card_ids": [],
            "status": "evidence_generated",
            "errors": [f"Evidence generation failed: {str(e)}"],
        }
