"""Regression coverage for security boundaries found during the full audit."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from academic_cluster.api.admin import providers
from academic_cluster.api.console.profile import (
    PasswordChangeRequest,
    change_password,
)
from academic_cluster.models.user import UserUpdate
from academic_cluster.services import url_security


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
