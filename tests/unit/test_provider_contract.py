"""Provider registry boundaries and environment seeding contracts."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from academic_cluster.api import main
from academic_cluster.api.admin import providers as provider_admin
from academic_cluster.api.admin.providers import (
    ProviderCreateRequest,
    ProviderUpdateRequest,
    list_providers,
)
from academic_cluster.services import crypto, provider_pool


class _Result:
    def __init__(
        self,
        *,
        rows: list[tuple[Any, ...]] | None = None,
        scalar_value: int | None = None,
    ) -> None:
        self._rows = rows or []
        self._scalar_value = scalar_value

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def scalar(self) -> int | None:
        return self._scalar_value


class _SessionContext:
    def __init__(self, session: Any) -> None:
        self._session = session

    async def __aenter__(self) -> Any:
        return self._session

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


class _Db:
    def __init__(self, session: Any) -> None:
        self.fake_session = session

    def session(self) -> _SessionContext:
        return _SessionContext(self.fake_session)


class _LegacyOnlyProviderSession:
    """Simulate a registry whose only physical row has kind=rerank."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: Any, params: Any = None) -> _Result:
        sql = str(statement)
        self.statements.append(sql)
        supported_filter = "kind IN ('llm', 'embedding', 'rerank')" in sql
        if "COUNT(*)" in sql:
            return _Result(scalar_value=1 if supported_filter else 0)
        legacy_row = (
            "rerank",
            "legacy-reranker",
            "https://legacy.invalid",
            "reranker",
            None,
            10,
            100,
        )
        return _Result(rows=[legacy_row] if supported_filter else [])


class _RecordingSession:
    def __init__(self, existing_rows: list[tuple[Any, ...]] | None = None) -> None:
        self.existing_rows = existing_rows or []
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        sql = str(statement)
        call_params = params or {}
        self.calls.append((sql, call_params))
        if "SELECT id, created_by, metadata" in sql:
            return _Result(rows=self.existing_rows)
        return _Result()


class _HttpResponse:
    status_code = 200
    text = ""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


class _HttpClient:
    def __init__(self, response: _HttpResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _HttpClient:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def post(self, *args: Any, **kwargs: Any) -> _HttpResponse:
        return self._response


def _provider_settings(api_key: str = "rotated-key") -> SimpleNamespace:
    return SimpleNamespace(
        llm_api_key=api_key,
        llm_base_url="https://new.example/v1",
        llm_provider="primary-llm",
        llm_model="new-model",
        embedding_api_key=None,
        llm_providers_json=None,
        embedding_providers_json=None,
    )


def test_provider_create_accepts_rerank_kind() -> None:
    request = ProviderCreateRequest(
        kind="rerank",
        display_name="primary-reranker",
        base_url="https://rerank.example/v1/rerank",
        model="rerank-model",
    )

    assert request.kind == "rerank"


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        "42",
        "null",
        '["not-an-object", null]',
        '[{"name":"missing-fields"}]',
        '[{"model":"", "api_key":"key"}]',
        '[{"model":"openai/", "api_key":"key"}]',
        '[{"model":"model", "api_key":""}]',
        '[{"model":"model", "api_key":"key", "rpm_limit":true}]',
        '[{"model":"model", "api_key":"key", "priority":true}]',
    ],
)
def test_provider_json_parser_rejects_invalid_or_incomplete_entries(raw: str) -> None:
    assert provider_pool._parse_litellm_model_list(raw, "llm") == []


def test_provider_priority_maps_higher_values_to_earlier_litellm_order() -> None:
    litellm = pytest.importorskip("litellm")
    models = provider_pool._parse_litellm_model_list(
        json.dumps(
            [
                {
                    "name": "preferred",
                    "model": "model",
                    "api_key": "preferred-key",
                    "priority": 200,
                },
                {
                    "name": "fallback",
                    "model": "model",
                    "api_key": "fallback-key",
                    "priority": 100,
                },
            ]
        ),
        "llm",
    )

    orders = {
        model["model_info"]["provider_alias"]: model["litellm_params"]["order"]
        for model in models
    }
    assert orders == {"preferred": -200, "fallback": -100}
    selected = litellm.utils._get_order_filtered_deployments(models)
    assert [model["model_info"]["provider_alias"] for model in selected] == [
        "preferred"
    ]


def test_provider_parser_normalizes_full_openai_endpoint_urls() -> None:
    llm_model = provider_pool._parse_litellm_model_list(
        json.dumps(
            [
                {
                    "name": "llm",
                    "model": "openai/chat-model",
                    "api_key": "llm-key",
                    "api_url": "https://provider.example/v1/chat/completions/",
                }
            ]
        ),
        "llm",
    )[0]
    embedding_model = provider_pool._parse_litellm_model_list(
        json.dumps(
            [
                {
                    "name": "embedding",
                    "model": "openai/embedding-model",
                    "api_key": "embedding-key",
                    "api_url": "https://provider.example/v1/embeddings",
                }
            ]
        ),
        "embedding",
    )[0]

    assert llm_model["model_name"] == "chat-model"
    assert llm_model["litellm_params"]["model"] == "openai/chat-model"
    assert llm_model["litellm_params"]["api_base"] == ("https://provider.example/v1")
    assert embedding_model["model_name"] == "embedding-model"
    assert embedding_model["litellm_params"]["model"] == ("openai/embedding-model")
    assert embedding_model["litellm_params"]["api_base"] == (
        "https://provider.example/v1"
    )


def test_provider_requests_reject_boolean_routing_limits() -> None:
    with pytest.raises(ValidationError):
        ProviderCreateRequest(
            kind="llm",
            display_name="provider",
            base_url="https://provider.example/v1",
            rpm_limit=True,
        )
    with pytest.raises(ValidationError):
        ProviderUpdateRequest(priority=True)


async def test_single_provider_fallback_canonicalizes_prefixed_models(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(
        is_production=False,
        llm_providers_json=None,
        llm_api_key="llm-key",
        llm_base_url="https://provider.example/v1/chat/completions",
        llm_model="openai/chat-model",
        llm_provider="llm-provider",
        embedding_providers_json=None,
        embedding_api_key="embedding-key",
        embedding_api_url="https://provider.example/v1/embeddings",
        embedding_model="openai/embedding-model",
        embedding_provider="embedding-provider",
    )

    async def _empty_registry() -> tuple[dict[str, list[dict[str, Any]]], bool]:
        return {"llm": [], "embedding": [], "rerank": []}, False

    monkeypatch.setattr(
        provider_pool,
        "_load_enabled_provider_configs_from_db",
        _empty_registry,
    )
    monkeypatch.setattr("academic_cluster.config.get_settings", lambda: settings)
    monkeypatch.setattr(provider_pool, "_llm_pool", None)
    monkeypatch.setattr(provider_pool, "_embedding_pool", None)

    await provider_pool.init_pools()

    llm = provider_pool.get_llm_pool().deployments[0]
    embedding = provider_pool.get_embedding_pool().deployments[0]
    assert llm["model_name"] == "chat-model"
    assert llm["litellm_params"]["model"] == "openai/chat-model"
    assert llm["litellm_params"]["api_base"] == "https://provider.example/v1"
    assert embedding["model_name"] == "embedding-model"
    assert embedding["litellm_params"]["model"] == "openai/embedding-model"
    assert embedding["litellm_params"]["api_base"] == ("https://provider.example/v1")


def test_litellm_router_enables_rate_checks_and_cooldowns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    litellm = pytest.importorskip("litellm")
    captured: dict[str, Any] = {}

    class _FakeRouter:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(litellm, "Router", _FakeRouter)
    pool = provider_pool.LiteLLMPool(
        "llm",
        [
            {
                "model_name": "model",
                "litellm_params": {
                    "model": "openai/model",
                    "api_key": "valid-key",
                    "rpm": 10,
                },
            }
        ],
    )

    pool._ensure_router()

    assert captured["enable_pre_call_checks"] is True
    assert captured["allowed_fails"] == 3
    assert captured["cooldown_time"] == 60
    assert captured["disable_cooldowns"] is False


async def test_provider_pool_loads_rerank_only_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _LegacyOnlyProviderSession()
    db = _Db(session)
    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: db,
    )

    (
        configs,
        registry_has_rows,
    ) = await provider_pool._load_enabled_provider_configs_from_db()

    assert registry_has_rows is True
    assert configs["llm"] == []
    assert configs["embedding"] == []
    assert configs["rerank"][0]["name"] == "legacy-reranker"
    assert configs["rerank"][0]["model"] == "reranker"
    assert len(session.statements) == 2
    assert all(
        "kind IN ('llm', 'embedding', 'rerank')" in statement
        for statement in session.statements
    )


async def test_production_init_clears_stale_pools_before_env_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stale_llm = provider_pool.LiteLLMPool("llm", [{"model_name": "stale"}])
    stale_embedding = provider_pool.LiteLLMPool("embedding", [{"model_name": "stale"}])
    settings = SimpleNamespace(
        is_production=True,
        llm_providers_json=None,
        llm_api_key=None,
        embedding_providers_json=None,
        embedding_api_key=None,
    )

    async def _empty_registry() -> tuple[dict[str, list[dict[str, Any]]], bool]:
        return {"llm": [], "embedding": [], "rerank": []}, False

    monkeypatch.setattr(provider_pool, "_llm_pool", stale_llm)
    monkeypatch.setattr(provider_pool, "_embedding_pool", stale_embedding)
    monkeypatch.setattr(
        provider_pool,
        "_load_enabled_provider_configs_from_db",
        _empty_registry,
    )
    monkeypatch.setattr("academic_cluster.config.get_settings", lambda: settings)

    with pytest.raises(RuntimeError, match="llm, embedding"):
        await provider_pool.init_pools()

    assert provider_pool._llm_pool is None
    assert provider_pool._embedding_pool is None


async def test_admin_listing_includes_rerank_when_requested() -> None:
    session = _RecordingSession()

    response = await list_providers(
        kind="rerank",
        admin={"id": "admin-id"},
        db=_Db(session),
    )

    assert response.total == 0
    sql, params = session.calls[0]
    assert "kind IN ('llm', 'embedding', 'rerank')" in sql
    assert "kind = :kind" in sql
    assert params == {"kind": "rerank"}


async def test_embedding_health_check_accepts_pgvector_compatible_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _HttpResponse({"data": [{"embedding": [0.25] * 1024}]})
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **_kwargs: _HttpClient(response),
    )

    await provider_admin._test_embedding(
        "https://embedding.example/v1",
        "api-key",
        "embedding-model",
    )


async def test_embedding_health_check_reports_configured_dimension_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _HttpResponse({"data": [{"embedding": [0.25] * 768}]})
    monkeypatch.setattr("httpx.AsyncClient", lambda **_kwargs: _HttpClient(response))

    with pytest.raises(RuntimeError, match="configured target is 1024") as error:
        await provider_admin._test_embedding(
            "https://embedding.example/v1",
            "api-key",
            "embedding-model",
        )
    assert "Set embedding.target_dimensions to 768" in str(error.value)


@pytest.mark.parametrize(
    ("vector", "error"),
    [
        ([float("nan")] + [0.25] * 1023, "non-finite values"),
        (["not-a-number"] + [0.25] * 1023, "non-numeric values"),
    ],
)
async def test_embedding_health_check_rejects_incompatible_vector(
    monkeypatch: pytest.MonkeyPatch,
    vector: list[Any],
    error: str,
) -> None:
    response = _HttpResponse({"data": [{"embedding": vector}]})
    monkeypatch.setattr(
        "httpx.AsyncClient",
        lambda **_kwargs: _HttpClient(response),
    )

    with pytest.raises(RuntimeError, match=error):
        await provider_admin._test_embedding(
            "https://embedding.example/v1",
            "api-key",
            "embedding-model",
        )


async def test_rerank_health_check_accepts_ranked_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _HttpResponse(
        {"results": [{"index": 0, "relevance_score": 0.99}]}
    )
    monkeypatch.setattr("httpx.AsyncClient", lambda **_kwargs: _HttpClient(response))

    await provider_admin._test_rerank(
        "https://rerank.example/v1",
        "api-key",
        "rerank-model",
    )


async def test_environment_seed_updates_and_reencrypts_legacy_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RecordingSession(existing_rows=[("provider-id", None, {})])
    monkeypatch.setattr(crypto, "encrypt_key", lambda value: f"encrypted::{value}")

    await main._seed_providers(_Db(session), _provider_settings())

    mutations = [
        call for call in session.calls if "UPDATE provider_registry" in call[0]
    ]
    assert len(mutations) == 1
    _, params = mutations[0]
    assert params["id"] == "provider-id"
    assert params["base_url"] == "https://new.example/v1"
    assert params["model"] == "new-model"
    assert params["api_key_enc"] == "encrypted::rotated-key"
    assert json.loads(params["metadata"]) == {"source": "environment"}
    assert not any("INSERT INTO provider_registry" in sql for sql, _ in session.calls)


async def test_environment_seed_preserves_admin_owned_same_name_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RecordingSession(
        existing_rows=[("provider-id", "admin-id", {"source": "admin"})]
    )
    monkeypatch.setattr(crypto, "encrypt_key", lambda value: f"encrypted::{value}")

    await main._seed_providers(_Db(session), _provider_settings())

    assert len(session.calls) == 1
    assert "SELECT id, created_by, metadata" in session.calls[0][0]


async def test_environment_seed_tags_new_provider_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RecordingSession()
    monkeypatch.setattr(crypto, "encrypt_key", lambda value: f"encrypted::{value}")

    await main._seed_providers(_Db(session), _provider_settings())

    inserts = [
        call for call in session.calls if "INSERT INTO provider_registry" in call[0]
    ]
    assert len(inserts) == 1
    _, params = inserts[0]
    assert params["api_key_enc"] == "encrypted::rotated-key"
    assert json.loads(params["metadata"]) == {"source": "environment"}


async def test_environment_seed_preserves_json_routing_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _RecordingSession()
    settings = _provider_settings(api_key="")
    settings.llm_providers_json = json.dumps(
        [
            {
                "name": "pooled-llm",
                "model": "pooled-model",
                "api_url": "https://pool.example/v1",
                "api_key": "pool-key",
                "rpm_limit": 37,
                "priority": 240,
            }
        ]
    )
    monkeypatch.setattr(crypto, "encrypt_key", lambda value: f"encrypted::{value}")

    await main._seed_providers(_Db(session), settings)

    insert = next(
        call for call in session.calls if "INSERT INTO provider_registry" in call[0]
    )
    assert insert[1]["rpm_limit"] == 37
    assert insert[1]["priority"] == 240


@pytest.mark.parametrize("field", ["rpm_limit", "priority"])
async def test_environment_seed_rejects_boolean_routing_limits(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    session = _RecordingSession()
    settings = _provider_settings(api_key="")
    settings.llm_providers_json = json.dumps(
        [
            {
                "name": "pooled-llm",
                "model": "pooled-model",
                "api_url": "https://pool.example/v1",
                "api_key": "pool-key",
                field: True,
            }
        ]
    )
    monkeypatch.setattr(crypto, "encrypt_key", lambda value: f"encrypted::{value}")

    await main._seed_providers(_Db(session), settings)

    assert session.calls == []


@pytest.mark.parametrize("raw", ["{}", "42", '"provider"'])
async def test_environment_seed_ignores_non_list_json(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    session = _RecordingSession()
    settings = _provider_settings(api_key="")
    settings.llm_providers_json = raw
    monkeypatch.setattr(crypto, "encrypt_key", lambda value: f"encrypted::{value}")

    await main._seed_providers(_Db(session), settings)

    assert session.calls == []


def test_production_crypto_fails_closed_without_key_even_if_cipher_is_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "academic_cluster.config.get_settings",
        lambda: SimpleNamespace(provider_encryption_key=None, is_production=True),
    )
    monkeypatch.setattr(crypto, "_fernet", Fernet(Fernet.generate_key()))

    with pytest.raises(RuntimeError, match="PROVIDER_ENCRYPTION_KEY"):
        crypto.encrypt_key("must-not-be-encrypted-with-an-ephemeral-key")
