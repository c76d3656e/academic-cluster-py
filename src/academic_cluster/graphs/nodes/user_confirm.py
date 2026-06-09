"""
用户确认节点 - 等待用户确认大纲

这是一个特殊的节点，图会在此处中断，等待用户确认大纲后继续执行。
"""

import structlog

from ..state import PipelineState

logger = structlog.get_logger()


async def user_confirm_node(state: PipelineState) -> dict:
    """
    用户确认大纲

    这是一个人工介入节点：
    - 图会在此处中断（通过 interrupt_before 配置）
    - 前端展示大纲给用户
    - 用户可以修改或确认大纲
    - 确认后图继续执行

    LangGraph 会自动处理中断和恢复逻辑。
    """
    logger.info("Waiting for user confirmation", outline_id=state.outline_id)

    # 这个节点实际上不需要做任何事情
    # LangGraph 的 interrupt 机制会自动处理
    # 用户确认后，状态会通过 config 传入

    logger.info("User confirmed outline")

    return {
        "status": "outline_confirmed",
    }
