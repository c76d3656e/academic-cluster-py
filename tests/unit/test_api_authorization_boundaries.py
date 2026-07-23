"""Regression tests for authentication and administrator invariants."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials

from academic_cluster.api import auth_routes, dependencies
from academic_cluster.api.admin import users as admin_users
from academic_cluster.services.database import DatabaseService


class _TokenWithoutSubject:
    def decode_access_token(self, token: str) -> dict[str, Any]:
        assert token == "signed-token"
        return {"type": "access"}


class _StaleToken:
    def decode_access_token(self, token: str) -> dict[str, Any]:
        assert token == "stale-token"
        return {"type": "access", "sub": "user-1", "ver": 3}


class _VersionedUserDatabase:
    async def get_user_by_id(self, user_id: str) -> dict[str, Any]:
        assert user_id == "user-1"
        return {
            "id": user_id,
            "email": "person@example.com",
            "role": "user",
            "is_active": True,
            "token_version": 4,
        }


class _UserDatabase:
    def __init__(self) -> None:
        self.role_updates: list[tuple[str, str]] = []
        self.active_updates: list[tuple[str, bool]] = []

    async def get_user_by_id(self, user_id: str) -> dict[str, Any]:
        return {
            "id": user_id,
            "email": "admin@example.com",
            "role": "admin",
            "is_active": True,
        }

    async def set_user_role(self, user_id: str, role: str) -> None:
        self.role_updates.append((user_id, role))

    async def set_user_active(self, user_id: str, is_active: bool) -> None:
        self.active_updates.append((user_id, is_active))


class _RefreshDatabase(_UserDatabase):
    def __init__(self) -> None:
        super().__init__()
        self.consumed: list[str] = []
        self.saved: list[tuple[str, str]] = []

    async def consume_refresh_token(self, token_hash: str) -> dict[str, str] | None:
        self.consumed.append(token_hash)
        return {"user_id": "user-1"} if token_hash == "refresh-hash" else None

    async def save_refresh_token(
        self, token_hash: str, user_id: str, expires_at: object
    ) -> str:
        del expires_at
        self.saved.append((token_hash, user_id))
        return "new-token-id"


class _RefreshTokenService:
    def hash_refresh_token(self, token: str) -> str:
        assert token == "raw-refresh"
        return "refresh-hash"

    def create_access_token(
        self, user_id: str, role: str, token_version: int = 0
    ) -> str:
        assert (user_id, role) == ("user-1", "admin")
        assert token_version == 0
        return "new-access"

    def create_refresh_token(self, user_id: str) -> tuple[str, str]:
        assert user_id == "user-1"
        return "new-refresh", "new-refresh-hash"


class _Result:
    def __init__(self, row: Any) -> None:
        self._row = row

    def fetchone(self) -> Any:
        return self._row


class _RefreshSession:
    def __init__(self, row: Any) -> None:
        self.row = row
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        self.statements.append((str(statement), params))
        return _Result(self.row)


class _DatabaseWithSession:
    def __init__(self, session: _RefreshSession) -> None:
        self._session = session

    @asynccontextmanager
    async def session(self):  # type: ignore[no-untyped-def]
        yield self._session


@pytest.mark.asyncio
async def test_access_token_without_subject_is_rejected_as_unauthorized() -> None:
    db = _UserDatabase()

    with pytest.raises(HTTPException) as caught:
        await dependencies.get_current_user(
            request=object(),  # type: ignore[arg-type]
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="signed-token"
            ),
            token_service=_TokenWithoutSubject(),  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 401


@pytest.mark.asyncio
async def test_access_token_is_rejected_after_session_version_changes() -> None:
    with pytest.raises(HTTPException) as caught:
        await dependencies.get_current_user(
            request=object(),  # type: ignore[arg-type]
            credentials=HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="stale-token"
            ),
            token_service=_StaleToken(),  # type: ignore[arg-type]
            db=_VersionedUserDatabase(),  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 401
    assert caught.value.detail == "Session has been revoked"


@pytest.mark.asyncio
async def test_admin_api_rejects_self_demotion() -> None:
    db = _UserDatabase()

    with pytest.raises(HTTPException) as caught:
        await admin_users.change_user_role(
            "admin-1",
            admin_users.ChangeRoleRequest(role="user"),
            request=object(),  # type: ignore[arg-type]
            admin={"id": "admin-1", "role": "admin"},
            db=db,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 400
    assert db.role_updates == []


def test_legacy_admin_auth_routes_are_removed() -> None:
    paths = {route.path for route in auth_routes.router.routes}
    assert paths.isdisjoint(
        {
            "/auth/users",
            "/auth/users/{user_id}/role",
            "/auth/users/{user_id}/active",
            "/auth/stats",
        }
    )


@pytest.mark.asyncio
async def test_refresh_route_consumes_rotated_token_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _RefreshDatabase()
    monkeypatch.setattr(
        auth_routes,
        "get_settings",
        lambda: SimpleNamespace(
            refresh_token_expire_days=7,
            refresh_cookie_name="academic_cluster_refresh",
            auth_allow_legacy_refresh_body=False,
            is_production=False,
        ),
    )

    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/refresh",
            "headers": [(b"cookie", b"academic_cluster_refresh=raw-refresh")],
        }
    )
    http_response = Response()

    response = await auth_routes.refresh_token(
        request=request,
        response=http_response,
        db=db,  # type: ignore[arg-type]
        token_service=_RefreshTokenService(),  # type: ignore[arg-type]
    )

    assert response.access_token == "new-access"
    assert "new-refresh" in http_response.headers["set-cookie"]
    assert "HttpOnly" in http_response.headers["set-cookie"]
    assert db.consumed == ["refresh-hash"]
    assert db.saved == [("new-refresh-hash", "user-1")]


@pytest.mark.asyncio
async def test_refresh_token_consumption_is_one_atomic_statement() -> None:
    row = SimpleNamespace(
        _mapping={"id": "token-1", "user_id": "user-1", "is_revoked": True}
    )
    session = _RefreshSession(row)
    db = _DatabaseWithSession(session)

    consumed = await DatabaseService.consume_refresh_token(  # type: ignore[arg-type]
        db, "refresh-hash"
    )

    assert consumed == {
        "id": "token-1",
        "user_id": "user-1",
        "is_revoked": True,
    }
    assert len(session.statements) == 1
    sql, params = session.statements[0]
    assert "UPDATE refresh_tokens" in sql
    assert "is_revoked = FALSE" in sql
    assert "RETURNING *" in sql
    assert params == {"token_hash": "refresh-hash"}
