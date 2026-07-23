"""Embedding-service unit tests."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from academic_cluster.services import embedding_service
from academic_cluster.services.observability import (
    pop_current_agent_phase,
    pop_current_execution,
    pop_current_project,
    push_current_agent_phase,
    push_current_execution,
    push_current_project,
)

DEFAULT_TEST_EMBEDDING_DIMENSIONS = 1024


class _FakeDatabase:
    def __init__(self, existing: set[str]) -> None:
        self.existing = existing
        self.requested_dimensions: int | None = None

    async def get_existing_embedding_paper_ids(
        self,
        paper_ids: list[str],
        *,
        model_name: str,
        dimensions: int | None = None,
    ) -> set[str]:
        assert model_name == "embedding-provider"
        self.requested_dimensions = dimensions
        return self.existing & set(paper_ids)


class _AuditDatabase:
    def __init__(self) -> None:
        self.created_calls: list[dict[str, Any]] = []
        self.finished_calls: list[dict[str, Any]] = []

    async def create_llm_call(self, **values: Any) -> str:
        self.created_calls.append(values)
        return "embedding-call-1"

    async def finish_llm_call(self, **values: Any) -> None:
        self.finished_calls.append(values)


class _FakeCache:
    async def get_embedding(self, paper_id: str, model_name: str) -> None:
        return None

    async def set_embedding(
        self,
        paper_id: str,
        model_name: str,
        embedding: list[float],
    ) -> None:
        return None


class _FakeVectorStore:
    def __init__(self) -> None:
        self.paper_ids: list[str] = []

    async def add_embeddings(
        self,
        paper_ids: list[str],
        embeddings: list[list[float]],
        model_name: str,
    ) -> None:
        self.paper_ids = paper_ids
        assert embeddings == [[0.1] * DEFAULT_TEST_EMBEDDING_DIMENSIONS]
        assert model_name == "embedding-provider"


@pytest.mark.asyncio
async def test_ensure_embeddings_only_generates_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDatabase({"p1"})
    fake_cache = _FakeCache()
    fake_store = _FakeVectorStore()
    embedding_request: dict[str, Any] = {}

    async def fake_embedding_request(**kwargs: Any) -> Any:
        embedding_request.update(kwargs)
        return SimpleNamespace(
            data=[{"embedding": [0.1] * DEFAULT_TEST_EMBEDDING_DIMENSIONS}]
        )

    fake_pool = SimpleNamespace(
        get_model_name=lambda: "embedding-provider",
        router=SimpleNamespace(aembedding=fake_embedding_request),
    )
    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: fake_db,
    )
    monkeypatch.setattr(
        "academic_cluster.services.cache.get_cache",
        lambda: fake_cache,
    )
    monkeypatch.setattr(
        "academic_cluster.services.vector_store.get_vector_store",
        lambda: fake_store,
    )
    monkeypatch.setattr(
        "academic_cluster.services.provider_pool.get_embedding_pool",
        lambda: fake_pool,
    )

    count = await embedding_service.ensure_paper_embeddings(
        [
            {"id": "p1", "title": "Existing"},
            {"id": "p2", "title": "Missing"},
            {"id": "p2", "title": "Duplicate"},
        ]
    )

    assert count == 2
    assert fake_store.paper_ids == ["p2"]
    assert fake_db.requested_dimensions == DEFAULT_TEST_EMBEDDING_DIMENSIONS
    assert embedding_request == {
        "model": "embedding-provider",
        "input": ["Missing"],
    }


@pytest.mark.asyncio
async def test_generate_embedding_accepts_litellm_model_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = [0.1] * DEFAULT_TEST_EMBEDDING_DIMENSIONS

    async def fake_embedding_request(**kwargs: Any) -> Any:
        assert kwargs == {"model": "embedding-provider", "input": ["paper text"]}
        return SimpleNamespace(data=[SimpleNamespace(embedding=expected)])

    fake_pool = SimpleNamespace(
        router=SimpleNamespace(aembedding=fake_embedding_request),
    )
    monkeypatch.setattr(
        "academic_cluster.services.provider_pool.get_embedding_pool",
        lambda: fake_pool,
    )

    result = await embedding_service._generate_embedding(
        "paper text",
        timeout=1.0,
        model_name="embedding-provider",
    )

    assert result == expected


@pytest.mark.asyncio
async def test_generate_embedding_persists_successful_provider_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = [0.1] * DEFAULT_TEST_EMBEDDING_DIMENSIONS
    db = _AuditDatabase()
    primary = {
        "model_name": "embedding-provider",
        "model_info": {"provider_alias": "primary"},
        "litellm_params": {
            "model": "openai/embedding-provider",
            "api_base": "https://primary.example/v1",
            "api_key": "primary-secret",
        },
    }
    selected = {
        "model_name": "embedding-provider",
        "model_info": {"provider_alias": "fallback"},
        "litellm_params": {
            "model": "openai/embedding-provider",
            "api_base": "https://fallback.example/v1",
            "api_key": "fallback-secret",
        },
    }

    async def fake_embedding_request(**_kwargs: Any) -> Any:
        return SimpleNamespace(
            data=[{"embedding": expected}],
            usage=SimpleNamespace(prompt_tokens=17, total_tokens=17),
            _hidden_params={"model_id": "fallback-id"},
        )

    router = SimpleNamespace(
        aembedding=fake_embedding_request,
        get_deployment=lambda model_id: selected if model_id == "fallback-id" else None,
    )
    fake_pool = SimpleNamespace(router=router, deployments=[primary])
    monkeypatch.setattr(
        "academic_cluster.services.provider_pool.get_embedding_pool",
        lambda: fake_pool,
    )
    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: db,
    )

    project_token = push_current_project("project-1")
    execution_token = push_current_execution("execution-1")
    phase_token = push_current_agent_phase("analysis")
    try:
        result = await embedding_service._generate_embedding(
            "paper text",
            timeout=1.0,
            model_name="embedding-provider",
        )
    finally:
        pop_current_agent_phase(phase_token)
        pop_current_execution(execution_token)
        pop_current_project(project_token)

    assert result == expected
    assert db.created_calls[0]["call_type"] == "embedding"
    assert db.created_calls[0]["project_id"] == "project-1"
    assert db.created_calls[0]["execution_id"] == "execution-1"
    assert db.created_calls[0]["node_name"] == "analysis"
    assert db.created_calls[0]["provider_name"] == "primary"
    assert db.finished_calls[0]["status"] == "success"
    assert db.finished_calls[0]["prompt_tokens"] == 17
    assert db.finished_calls[0]["completion_tokens"] == 0
    assert db.finished_calls[0]["provider_name"] == "fallback"
    assert db.finished_calls[0]["api_base_url"] == "https://fallback.example/v1"


@pytest.mark.asyncio
async def test_generate_embedding_persists_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _AuditDatabase()

    async def failed_embedding_request(**_kwargs: Any) -> Any:
        raise RuntimeError("embedding provider unavailable")

    fake_pool = SimpleNamespace(
        router=SimpleNamespace(aembedding=failed_embedding_request),
        deployments=[],
    )
    monkeypatch.setattr(
        "academic_cluster.services.provider_pool.get_embedding_pool",
        lambda: fake_pool,
    )
    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: db,
    )

    project_token = push_current_project("project-1")
    execution_token = push_current_execution("execution-1")
    phase_token = push_current_agent_phase("analysis")
    try:
        with pytest.raises(RuntimeError, match="embedding provider unavailable"):
            await embedding_service._generate_embedding(
                "paper text",
                timeout=1.0,
                model_name="embedding-provider",
            )
    finally:
        pop_current_agent_phase(phase_token)
        pop_current_execution(execution_token)
        pop_current_project(project_token)

    assert db.created_calls[0]["call_type"] == "embedding"
    assert db.finished_calls == [
        {
            "call_id": "embedding-call-1",
            "status": "error",
            "error_message": "embedding provider unavailable",
            "latency_ms": db.finished_calls[0]["latency_ms"],
        }
    ]


@pytest.mark.parametrize(
    "values",
    [
        [],
        [float("nan")] * DEFAULT_TEST_EMBEDDING_DIMENSIONS,
        [True] * DEFAULT_TEST_EMBEDDING_DIMENSIONS,
        "not-a-vector",
    ],
)
def test_embedding_validation_rejects_incompatible_vectors(values: Any) -> None:
    with pytest.raises(RuntimeError):
        embedding_service._validated_embedding(values)


def test_embedding_validation_explains_configured_dimension_mismatch() -> None:
    with pytest.raises(RuntimeError, match="configured target is 1024") as error:
        embedding_service._validated_embedding(
            [0.1] * 4086,
            expected_dimensions=1024,
        )

    assert "Set embedding.target_dimensions to 4086" in str(error.value)


def test_embedding_validation_accepts_supported_high_dimension_vector() -> None:
    vector = embedding_service._validated_embedding(
        [0.1] * 4086,
        expected_dimensions=4086,
    )

    assert len(vector) == 4086


@pytest.mark.asyncio
async def test_ensure_embeddings_rejects_empty_papers() -> None:
    assert await embedding_service.ensure_paper_embeddings([]) == 0
    assert (
        await embedding_service.ensure_paper_embeddings(
            [{"id": "p1", "title": "", "abstract": ""}]
        )
        == 0
    )


@pytest.mark.asyncio
async def test_embedding_failure_cancels_sibling_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_db = _FakeDatabase(set())
    fake_cache = _FakeCache()
    sibling_started = asyncio.Event()
    sibling_cancelled = asyncio.Event()

    async def fake_generate(
        text: str,
        _timeout: float,
        _model_name: str,
        _expected_dimensions: int | None = None,
    ) -> list[float]:
        if text == "fails":
            await sibling_started.wait()
            raise RuntimeError("provider failure")
        sibling_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            sibling_cancelled.set()
        return [0.1] * DEFAULT_TEST_EMBEDDING_DIMENSIONS

    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: fake_db,
    )
    monkeypatch.setattr(
        "academic_cluster.services.cache.get_cache",
        lambda: fake_cache,
    )
    monkeypatch.setattr(embedding_service, "_generate_embedding", fake_generate)

    with pytest.raises(ExceptionGroup):
        await embedding_service.ensure_paper_embeddings(
            [
                {"id": "p1", "title": "fails"},
                {"id": "p2", "title": "waits"},
            ],
            concurrency=2,
            model_name="embedding-provider",
        )

    assert sibling_cancelled.is_set()
