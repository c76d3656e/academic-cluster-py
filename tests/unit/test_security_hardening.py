"""Regression coverage for security boundaries found during the full audit."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from academic_cluster.api import auth_routes
from academic_cluster.api.admin import providers
from academic_cluster.api.console.profile import (
    PasswordChangeRequest,
    change_password,
)
from academic_cluster.api.dependencies import project_access_allowed
from academic_cluster.models.user import UserCreate, UserUpdate
from academic_cluster.services import rate_limit, url_security
from academic_cluster.services.tenant_context import (
    clear_tenant_context,
    get_tenant_context,
    set_tenant_context,
)


class _PasswordService:
    def verify_password(self, password: str, hashed: str) -> bool:
        return (password, hashed) == ("current-password", "stored-hash")

    def hash_password(self, password: str) -> str:
        assert password == "replacement-password"
        return "replacement-hash"


class _PasswordDatabase:
    def __init__(self) -> None:
        self.updated: list[tuple[str, dict[str, Any]]] = []
        self.revoked: list[str] = []
        self.activities: list[tuple[str, str]] = []

    async def update_user(self, user_id: str, values: dict[str, Any]) -> None:
        self.updated.append((user_id, values))

    async def revoke_all_user_tokens(self, user_id: str) -> None:
        self.revoked.append(user_id)

    async def log_activity(self, user_id: str, action: str) -> None:
        self.activities.append((user_id, action))


def _url_settings(**overrides: Any) -> SimpleNamespace:
    values = {
        "provider_allow_insecure_http": False,
        "provider_allow_private_networks": False,
        "provider_allowed_host_list": [],
        "is_production": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_profile_update_rejects_password_field() -> None:
    with pytest.raises(ValidationError, match="password"):
        UserUpdate(
            full_name="Researcher",
            password="stolen-access-token",  # noqa: S106 - rejected input fixture
        )


async def test_password_change_revokes_sessions_and_records_audit() -> None:
    db = _PasswordDatabase()

    response = await change_password(
        PasswordChangeRequest(
            current_password="current-password",  # noqa: S106 - auth fixture
            new_password="replacement-password",  # noqa: S106 - auth fixture
        ),
        current_user={"id": "user-1", "hashed_password": "stored-hash"},
        db=db,  # type: ignore[arg-type]
        password_service=_PasswordService(),  # type: ignore[arg-type]
    )

    assert response["message"]
    assert db.updated == [("user-1", {"hashed_password": "replacement-hash"})]
    assert db.revoked == ["user-1"]
    assert db.activities == [("user-1", "password.change")]


@pytest.mark.parametrize(
    "url",
    [
        "http://provider.example/v1",
        "https://user:secret@provider.example/v1",
        "https://127.0.0.1/v1",
        "https://169.254.169.254/latest/meta-data",
        "https://localhost/v1",
    ],
)
def test_provider_url_syntax_rejects_unsafe_destinations(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
) -> None:
    monkeypatch.setattr(url_security, "get_settings", lambda: _url_settings())

    with pytest.raises(url_security.UnsafeOutboundUrlError):
        url_security.validate_outbound_url_syntax(url)


async def test_provider_url_rejects_dns_resolving_to_private_address(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(url_security, "get_settings", lambda: _url_settings())

    async def _private_resolution(_host: str, _port: int) -> set[str]:
        return {"10.0.0.9"}

    monkeypatch.setattr(url_security, "_resolve_host_addresses", _private_resolution)
    with pytest.raises(url_security.UnsafeOutboundUrlError, match="non-public"):
        await url_security.validate_outbound_url("https://provider.example/v1")


async def test_provider_url_change_requires_api_key_rotation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "academic_cluster.services.url_security.get_settings",
        lambda: _url_settings(),
    )

    with pytest.raises(HTTPException) as caught:
        await providers.update_provider(
            "provider-1",
            providers.ProviderUpdateRequest(base_url="https://provider.example/v1"),
            admin={"id": "admin-1"},
            db=object(),  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 422
    assert "API key" in str(caught.value.detail)


async def test_public_registration_is_disabled_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_routes,
        "get_settings",
        lambda: SimpleNamespace(registration_enabled=False),
    )
    with pytest.raises(HTTPException) as caught:
        await auth_routes.register(
            UserCreate(
                email="person@example.com",
                password="registration-password",  # noqa: S106 - rejected fixture
            ),
            request=object(),  # type: ignore[arg-type]
            db=object(),  # type: ignore[arg-type]
            password_service=object(),  # type: ignore[arg-type]
        )
    assert caught.value.status_code == 403


def test_project_access_uses_active_organization_not_only_owner() -> None:
    project = {
        "id": "project-1",
        "user_id": "owner-1",
        "organization_id": "organization-1",
    }
    member = {
        "id": "member-1",
        "role": "user",
        "active_organization_id": "organization-1",
    }
    outsider = {
        "id": "owner-1",
        "role": "user",
        "active_organization_id": "organization-2",
    }

    assert project_access_allowed(project, member) is True
    assert project_access_allowed(project, outsider) is False


def test_tenant_context_is_request_local_and_clearable() -> None:
    clear_tenant_context()
    set_tenant_context(
        user_id="user-1", organization_id="organization-1", is_admin=False
    )
    assert get_tenant_context().organization_id == "organization-1"
    clear_tenant_context()
    assert get_tenant_context().organization_id is None


async def test_rate_limiter_uses_atomic_redis_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Redis:
        async def eval(self, *_args: Any) -> list[int]:
            return [3, 41]

    monkeypatch.setattr(
        rate_limit,
        "get_cache",
        lambda: SimpleNamespace(redis=_Redis()),
    )
    result = await rate_limit.RateLimiter().check(
        "login:203.0.113.10", limit=5, window_seconds=60
    )
    assert result.allowed is True
    assert result.remaining == 2
    assert result.retry_after == 41


def test_security_migration_enables_rls_for_project_artifacts() -> None:
    from pathlib import Path

    sql = (
        Path(__file__).parents[2] / "scripts" / "migrate_security.sql"
    ).read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS organizations" in sql
    assert "CREATE TABLE IF NOT EXISTS organization_memberships" in sql
    assert "ALTER TABLE projects FORCE ROW LEVEL SECURITY" in sql
    assert "CREATE POLICY tenant_isolation ON projects" in sql
    assert "ALTER TABLE llm_calls FORCE ROW LEVEL SECURITY" in sql
    assert "app_project_access(project_id)" in sql
