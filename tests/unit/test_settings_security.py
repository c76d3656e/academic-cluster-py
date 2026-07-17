"""Production settings and readiness must fail closed."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import Response

from academic_cluster.api import main
from academic_cluster.config.settings import RedisSettings, Settings
from academic_cluster.services import provider_pool
from academic_cluster.services.database import build_database_url


def _valid_production_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "app_env": "production",
        "app_debug": False,
        "cors_origins": "https://example.test",
        "jwt_secret_key": "j" * 48,
        "jwt_algorithm": "HS256",
        "postgres_password": "database-password-strong",
        "redis_password": "redis-password-strong",
        "admin_password": "administrator-password-strong",
        "provider_encryption_key": "provider-encryption-password-stable",
        "llm_api_key": None,
        "llm_providers_json": None,
        "embedding_api_key": None,
        "embedding_providers_json": None,
        "langfuse_enabled": False,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_valid_production_security_configuration_passes() -> None:
    _valid_production_settings().validate_security()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("jwt_secret_key", "your_jwt_secret_key_here"),
        ("postgres_password", "your_postgres_password_here"),
        ("redis_password", "your_redis_password_here"),
        ("admin_password", ""),
        ("provider_encryption_key", None),
        ("provider_encryption_key", "your_provider_encryption_key_here"),
        ("llm_api_key", "your_openai_api_key_here"),
        ("embedding_api_key", "your_embedding_api_key_here"),
        ("app_debug", True),
        ("jwt_algorithm", "none"),
        ("cors_origins", "https://example.test,*"),
    ],
)
def test_production_rejects_missing_weak_or_placeholder_secrets(
    field: str,
    value: Any,
) -> None:
    settings = _valid_production_settings(**{field: value})

    with pytest.raises(RuntimeError, match=field):
        settings.validate_security()


def test_production_rejects_placeholder_provider_json_key() -> None:
    settings = _valid_production_settings(
        llm_providers_json=(
            '[{"name":"llm","model":"model","api_key":"your_key_here"}]'
        )
    )

    with pytest.raises(RuntimeError, match="llm_providers_json"):
        settings.validate_security()


def test_development_allows_provider_configuration_after_startup() -> None:
    Settings(_env_file=None, app_env="development").validate_security()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("langfuse_public_key", "your_langfuse_public_key"),
        ("langfuse_secret_key", "your_langfuse_secret_key"),
        ("langfuse_base_url", "http://langfuse.internal"),
        ("langfuse_base_url", "https://user:password@langfuse.internal"),
        ("langfuse_tracing_environment", "Production Environment"),
        ("langfuse_tracing_environment", "langfuse-production"),
    ],
)
def test_enabled_production_langfuse_requires_secure_configuration(
    field: str,
    value: str,
) -> None:
    langfuse_settings = {
        "langfuse_enabled": True,
        "langfuse_public_key": "pk-lf-production-key",
        "langfuse_secret_key": "sk-lf-production-secret",
        "langfuse_base_url": "https://langfuse.example.test",
        field: value,
    }
    settings = _valid_production_settings(**langfuse_settings)

    with pytest.raises(RuntimeError, match=field):
        settings.validate_security()


def test_enabled_production_langfuse_accepts_explicit_secure_configuration() -> None:
    settings = _valid_production_settings(
        langfuse_enabled=True,
        langfuse_public_key="pk-lf-production-key",
        langfuse_secret_key="sk-lf-production-secret",  # noqa: S106 - fixture
        langfuse_base_url="https://langfuse.example.test",
    )

    settings.validate_security()


def test_redis_url_percent_encodes_password_delimiters() -> None:
    settings = RedisSettings(
        host="redis.internal",
        port=6380,
        password="p@ss:/?#%",  # noqa: S106 - delimiter encoding fixture
        db=2,
    )

    assert settings.url == "redis://:p%40ss%3A%2F%3F%23%25@redis.internal:6380/2"


def test_postgres_url_percent_encodes_credentials() -> None:
    url = build_database_url(
        SimpleNamespace(
            postgres_user="user@tenant",
            postgres_password="p@ss:word/?#[]",  # noqa: S106 - URL fixture
            postgres_host="postgres",
            postgres_port=5432,
            postgres_db="academic_cluster",
        )
    )

    assert url.username == "user@tenant"
    assert url.password == "p@ss:word/?#[]"
    rendered = url.render_as_string(hide_password=False)
    assert "user%40tenant" in rendered
    assert "p%40ss%3Aword%2F%3F%23%5B%5D" in rendered


def test_cors_origins_accept_csv_and_legacy_json_array() -> None:
    csv_settings = Settings(
        _env_file=None,
        cors_origins="http://localhost:3000,https://example.test",
    )
    json_settings = Settings(
        _env_file=None,
        cors_origins='["http://localhost:3000", "https://example.test"]',
    )

    expected = ["http://localhost:3000", "https://example.test"]
    assert csv_settings.cors_origin_list == expected
    assert json_settings.cors_origin_list == expected


def test_debug_wildcard_cors_disables_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(_env_file=None, app_debug=True, cors_origins=None),
    )

    app = main.create_app()
    middleware = next(
        item
        for item in app.user_middleware
        if getattr(item.cls, "__name__", "") == "CORSMiddleware"
    )

    assert middleware.kwargs["allow_origins"] == ["*"]
    assert middleware.kwargs["allow_credentials"] is False


def test_required_provider_pool_check_reports_every_missing_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(provider_pool, "_llm_pool", None)
    monkeypatch.setattr(provider_pool, "_embedding_pool", None)

    with pytest.raises(RuntimeError, match="llm, embedding"):
        provider_pool.require_agent_provider_pools()


async def test_health_is_unhealthy_without_agent_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = main.create_app()
    endpoint = next(
        route.endpoint
        for route in app.routes
        if getattr(route, "path", "") == "/health"
    )
    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.is_checkpointer_initialized",
        lambda: False,
    )
    monkeypatch.setattr(provider_pool, "_llm_pool", None)
    monkeypatch.setattr(provider_pool, "_embedding_pool", None)
    response = Response()

    payload = await endpoint(response)

    assert response.status_code == 503
    assert payload["status"] == "unhealthy"
    assert "checkpoint" in payload["issues"]
