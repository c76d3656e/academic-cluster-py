"""
SSE (Server-Sent Events) 实时推送服务

用于向前端推送 Agent 执行进度、错误和完成事件。
"""

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator

import structlog
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from ..services.auth import get_token_service
from ..services.database import get_database

logger = structlog.get_logger()

router = APIRouter()


class SSEConnectionLimitError(RuntimeError):
    """Raised when a project exceeds its bounded SSE connection count."""


class SSEManager:
    """SSE connection manager with bounded slow-consumer backpressure."""

    def __init__(
        self,
        *,
        max_queue_events: int | None = None,
        max_connections_per_project: int | None = None,
    ) -> None:
        from ..config import get_settings

        settings = get_settings()
        self._max_queue_events = (
            settings.sse_max_queue_events
            if max_queue_events is None
            else max_queue_events
        )
        self._max_connections_per_project = (
            settings.sse_max_connections_per_project
            if max_connections_per_project is None
            else max_connections_per_project
        )
        if self._max_queue_events < 1:
            raise ValueError("max_queue_events must be at least one")
        if self._max_connections_per_project < 1:
            raise ValueError("max_connections_per_project must be at least one")
        self._connections: dict[str, list[asyncio.Queue[dict[str, object]]]] = {}

    async def connect(self, project_id: str) -> asyncio.Queue[dict[str, object]]:
        """Create a bounded SSE connection or reject a connection flood."""

        connections = self._connections.setdefault(project_id, [])
        if len(connections) >= self._max_connections_per_project:
            raise SSEConnectionLimitError("Too many SSE connections for this project")
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(
            maxsize=self._max_queue_events
        )

        connections.append(queue)

        logger.info("SSE client connected", project_id=project_id)
        return queue

    async def disconnect(
        self, project_id: str, queue: asyncio.Queue[dict[str, object]]
    ) -> None:
        """断开 SSE 连接"""
        if project_id in self._connections:
            try:
                self._connections[project_id].remove(queue)
            except ValueError:
                return
            if not self._connections[project_id]:
                del self._connections[project_id]

        logger.info("SSE client disconnected", project_id=project_id)

    async def send_event(
        self, project_id: str, event_type: str, data: dict[str, object]
    ) -> None:
        """
        发送事件到指定项目的所有连接

        Args:
            project_id: 项目 ID
            event_type: 事件类型
            data: 事件数据
        """
        if project_id not in self._connections:
            return

        event: dict[str, object] = {
            "type": event_type,
            "data": data,
        }

        dropped = 0
        for queue in list(self._connections[project_id]):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Progress is lossy by design: a slow browser only needs the
                # newest state, except that an already queued terminal/error
                # event must survive a later progress update.
                previous: dict[str, object] | None = None
                with contextlib.suppress(asyncio.QueueEmpty):
                    previous = queue.get_nowait()
                if (
                    event_type == "progress"
                    and previous is not None
                    and previous.get("type") in {"error", "complete"}
                ):
                    queue.put_nowait(previous)
                    dropped += 1
                    continue
                queue.put_nowait(event)
                dropped += 1

        logger.debug(
            "SSE event sent",
            project_id=project_id,
            event_type=event_type,
            clients=len(self._connections[project_id]),
            dropped_slow_consumer_events=dropped,
        )

    async def send_progress(
        self,
        project_id: str,
        node: str,
        status: str,
        progress: float = 0.0,
        message: str = "",
        detail: dict[str, object] | None = None,
    ) -> None:
        """发送进度事件"""
        data: dict[str, object] = {
            "node": node,
            "status": status,
            "progress": progress,
            "message": message,
        }
        if detail:
            data["detail"] = detail
        await self.send_event(project_id, "progress", data)

    async def send_error(self, project_id: str, error: str) -> None:
        """发送错误事件"""
        await self.send_event(project_id, "error", {"message": error})

    async def send_complete(self, project_id: str, result: dict[str, object]) -> None:
        """发送完成事件"""
        await self.send_event(project_id, "complete", result)


# 全局 SSE 管理器
_sse_manager: SSEManager | None = None


def get_sse_manager() -> SSEManager:
    """获取 SSE 管理器单例"""
    global _sse_manager
    if _sse_manager is None:
        _sse_manager = SSEManager()
    return _sse_manager


async def sse_generator(
    project_id: str,
    request: Request,
    queue: asyncio.Queue[dict[str, object]] | None = None,
) -> AsyncGenerator[str, None]:
    """SSE 事件生成器"""
    manager = get_sse_manager()
    if queue is None:
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
                data = json.dumps(event.get("data", {}), ensure_ascii=False)

                yield f"event: {event_type}\ndata: {data}\n\n"

            except TimeoutError:
                # 发送心跳
                yield ": heartbeat\n\n"

    finally:
        await manager.disconnect(project_id, queue)


@router.get("/stream/{project_id}")
async def stream_events(
    project_id: str,
    request: Request,
    authorization: str | None = Header(default=None),
) -> StreamingResponse:
    """Stream project progress using a Bearer header, never a URL token."""

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.removeprefix("Bearer ").strip()
    if not token:
        raise HTTPException(status_code=401, detail="Bearer token required")

    token_service = get_token_service()
    try:
        payload = token_service.decode_access_token(token)
        user_id = str(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=401, detail="Invalid or expired token"
        ) from None

    db = get_database()
    user = await db.get_user_by_id(user_id)
    if not user or not user.get("is_active", False):
        raise HTTPException(status_code=401, detail="User not found or deactivated")
    if int(payload.get("ver") or 0) != int(user.get("token_version") or 0):
        raise HTTPException(status_code=401, detail="Session has been revoked")

    from ..services.tenant_context import set_tenant_context
    from .dependencies import project_access_allowed

    organization_id = user.get("default_organization_id")
    user["active_organization_id"] = organization_id
    set_tenant_context(
        user_id=user_id,
        organization_id=str(organization_id) if organization_id else None,
        is_admin=user.get("role") == "admin",
    )
    project = await db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if not project_access_allowed(project, user):
        raise HTTPException(status_code=403, detail="Access denied")

    manager = get_sse_manager()
    try:
        queue = await manager.connect(project_id)
    except SSEConnectionLimitError as error:
        raise HTTPException(status_code=429, detail=str(error)) from error

    return StreamingResponse(
        sse_generator(project_id, request, queue),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
