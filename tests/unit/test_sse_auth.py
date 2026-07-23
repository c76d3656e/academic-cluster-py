"""SSE authorization must not accept credentials in URLs."""

from typing import Any

import pytest
from fastapi import HTTPException

from academic_cluster.api import sse


class _TokenService:
    def decode_access_token(self, token: str) -> dict[str, str]:
        assert token == "valid-token"
        return {"sub": "user-1"}


class _Database:
    def __init__(self, project: dict[str, Any] | None) -> None:
        self.project = project

    async def get_user_by_id(self, user_id: str) -> dict[str, Any]:
        assert user_id == "user-1"
        return {"id": "user-1", "role": "user", "is_active": True}

    async def get_project(self, project_id: str) -> dict[str, Any] | None:
        assert project_id == "project-1"
        return self.project


@pytest.mark.asyncio
async def test_sse_requires_bearer_header() -> None:
    with pytest.raises(HTTPException) as caught:
        await sse.stream_events(
            "project-1",
            request=object(),  # type: ignore[arg-type]
            authorization=None,
        )

    assert caught.value.status_code == 401


@pytest.mark.asyncio
async def test_sse_rejects_unknown_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sse, "get_token_service", _TokenService)
    monkeypatch.setattr(sse, "get_database", lambda: _Database(None))

    with pytest.raises(HTTPException) as caught:
        await sse.stream_events(
            "project-1",
            request=object(),  # type: ignore[arg-type]
            authorization="Bearer valid-token",
        )

    assert caught.value.status_code == 404


@pytest.mark.asyncio
async def test_sse_accepts_authorized_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sse, "get_token_service", _TokenService)
    monkeypatch.setattr(
        sse,
        "get_database",
        lambda: _Database({"id": "project-1", "user_id": "user-1"}),
    )

    response = await sse.stream_events(
        "project-1",
        request=object(),  # type: ignore[arg-type]
        authorization="Bearer valid-token",
    )

    assert response.media_type == "text/event-stream"


@pytest.mark.asyncio
async def test_sse_replaces_old_events_for_a_slow_consumer() -> None:
    manager = sse.SSEManager(max_queue_events=1, max_connections_per_project=2)
    queue = await manager.connect("project-1")

    await manager.send_progress("project-1", "research", "running", progress=0.1)
    await manager.send_progress("project-1", "analysis", "running", progress=0.8)

    event = queue.get_nowait()
    assert event["type"] == "progress"
    assert event["data"]["node"] == "analysis"

    await manager.send_error("project-1", "provider unavailable")
    await manager.send_progress("project-1", "finalize", "running", progress=0.9)
    terminal = queue.get_nowait()
    assert terminal["type"] == "error"


@pytest.mark.asyncio
async def test_sse_enforces_per_project_connection_limit() -> None:
    manager = sse.SSEManager(max_queue_events=2, max_connections_per_project=1)
    await manager.connect("project-1")

    with pytest.raises(sse.SSEConnectionLimitError):
        await manager.connect("project-1")
