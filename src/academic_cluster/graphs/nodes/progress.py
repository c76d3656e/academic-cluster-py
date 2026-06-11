"""节点级进度推送工具

提供轻量级的 SSE 进度推送函数，失败时不影响节点执行。
"""

import structlog

from ...api.sse import get_sse_manager

logger = structlog.get_logger()


async def send_progress(
    project_id: str,
    node: str,
    message: str,
    detail: dict | None = None,
    progress: float = 0.0,
):
    """发送节点级进度事件（容错：失败不影响节点执行）

    Args:
        project_id: 项目 ID
        node: 节点名称
        message: 进度消息
        detail: 可选的附加数据
        progress: 进度百分比 0.0~1.0
    """
    try:
        sse = get_sse_manager()
        await sse.send_progress(
            project_id=project_id,
            node=node,
            status="processing",
            progress=progress,
            message=message,
            detail=detail,
        )
        logger.debug("progress_sent", node=node, message=message)
    except Exception as e:
        logger.debug("progress_send_failed", node=node, error=str(e))
