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
