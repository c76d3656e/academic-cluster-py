"""
证据卡片节点 - 为论文生成结构化证据卡片
"""

import structlog

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

    # TODO: 实现证据卡片生成
    # 1. 从数据库获取核心论文详情
    # 2. 批量调用 LLM 生成证据卡片
    # 3. 存储到数据库
    # 4. 返回证据卡片 ID 列表

    evidence_card_ids = []

    logger.info(
        "Evidence card generation completed",
        cards=len(evidence_card_ids),
    )

    return {
        "evidence_card_ids": evidence_card_ids,
        "status": "evidence_generated",
    }
