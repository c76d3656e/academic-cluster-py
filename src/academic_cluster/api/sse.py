"""
SSE (Server-Sent Events) 实时推送服务

用于向前端推送 Pipeline 执行状态和社区可视化数据。
"""

import asyncio
import json
from typing import AsyncGenerator, Optional

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

logger = structlog.get_logger()

router = APIRouter()


class SSEManager:
    """SSE 连接管理器"""

    def __init__(self):
        self._connections: dict[str, list[asyncio.Queue]] = {}

    async def connect(self, project_id: str) -> asyncio.Queue:
        """创建新的 SSE 连接"""
        queue = asyncio.Queue()

        if project_id not in self._connections:
            self._connections[project_id] = []

        self._connections[project_id].append(queue)

        logger.info("SSE client connected", project_id=project_id)
        return queue

    async def disconnect(self, project_id: str, queue: asyncio.Queue):
        """断开 SSE 连接"""
        if project_id in self._connections:
            self._connections[project_id].remove(queue)
            if not self._connections[project_id]:
                del self._connections[project_id]

        logger.info("SSE client disconnected", project_id=project_id)

    async def send_event(self, project_id: str, event_type: str, data: dict):
        """
        发送事件到指定项目的所有连接

        Args:
            project_id: 项目 ID
            event_type: 事件类型
            data: 事件数据
        """
        if project_id not in self._connections:
            return

        event = {
            "type": event_type,
            "data": data,
        }

        for queue in self._connections[project_id]:
            await queue.put(event)

        logger.debug(
            "SSE event sent",
            project_id=project_id,
            event_type=event_type,
            clients=len(self._connections[project_id]),
        )

    async def send_progress(
        self,
        project_id: str,
        node: str,
        status: str,
        progress: float = 0.0,
        message: str = "",
    ):
        """发送进度事件"""
        await self.send_event(project_id, "progress", {
            "node": node,
            "status": status,
            "progress": progress,
            "message": message,
        })

    async def send_community_visualization(self, project_id: str, visualization: dict):
        """发送社区可视化数据"""
        await self.send_event(project_id, "community_visualization", visualization)

    async def send_outline(self, project_id: str, outline: dict):
        """发送大纲数据"""
        await self.send_event(project_id, "outline", outline)

    async def send_error(self, project_id: str, error: str):
        """发送错误事件"""
        await self.send_event(project_id, "error", {"message": error})

    async def send_complete(self, project_id: str, result: dict):
        """发送完成事件"""
        await self.send_event(project_id, "complete", result)


# 全局 SSE 管理器
_sse_manager: Optional[SSEManager] = None


def get_sse_manager() -> SSEManager:
    """获取 SSE 管理器单例"""
    global _sse_manager
    if _sse_manager is None:
        _sse_manager = SSEManager()
    return _sse_manager


async def sse_generator(
    project_id: str,
    request: Request,
) -> AsyncGenerator[str, None]:
    """SSE 事件生成器"""
    manager = get_sse_manager()
    queue = await manager.connect(project_id)

    try:
        # 发送连接成功事件
        yield f"event: connected\ndata: {json.dumps({'project_id': project_id})}\n\n"

        while True:
            # 检查客户端是否断开
            if await request.is_disconnected():
                break

            try:
                # 等待事件，设置超时以检查客户端断开
                event = await asyncio.wait_for(queue.get(), timeout=30.0)

                event_type = event.get("type", "message")
                data = json.dumps(event.get("data", {}))

                yield f"event: {event_type}\ndata: {data}\n\n"

            except asyncio.TimeoutError:
                # 发送心跳
                yield ": heartbeat\n\n"

    finally:
        await manager.disconnect(project_id, queue)


@router.get("/stream/{project_id}")
async def stream_events(project_id: str, request: Request):
    """
    SSE 端点

    客户端可以通过 EventSource 连接此端点接收实时更新。

    示例：
    ```javascript
    const eventSource = new EventSource('/api/stream/project-id');
    eventSource.addEventListener('progress', (e) => {
        const data = JSON.parse(e.data);
        console.log('Progress:', data);
    });
    eventSource.addEventListener('community_visualization', (e) => {
        const data = JSON.parse(e.data);
        // 渲染可视化
    });
    ```
    """
    return StreamingResponse(
        sse_generator(project_id, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
