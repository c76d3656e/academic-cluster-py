"""Embedding-service unit tests."""

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from academic_cluster.services import embedding_service


class _FakeDatabase:
    def __init__(self, existing: set[str]) -> None:
        self.existing = existing

    async def get_existing_embedding_paper_ids(
        self,
        paper_ids: list[str],
        *,
        model_name: str,
    ) -> set[str]:
        assert model_name == "embedding-provider"
        return self.existing & set(paper_ids)


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
        assert embeddings == [[0.1] * embedding_service.EMBEDDING_DIMENSIONS]
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
            data=[{"embedding": [0.1] * embedding_service.EMBEDDING_DIMENSIONS}]
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
    assert embedding_request == {
        "model": "embedding-provider",
        "input": ["Missing"],
    }


@pytest.mark.asyncio
async def test_generate_embedding_accepts_litellm_model_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = [0.1] * embedding_service.EMBEDDING_DIMENSIONS

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


@pytest.mark.parametrize(
    "values",
    [
        [],
        [0.1, 0.2],
        [float("nan")] * embedding_service.EMBEDDING_DIMENSIONS,
        [True] * embedding_service.EMBEDDING_DIMENSIONS,
        "not-a-vector",
    ],
)
def test_embedding_validation_rejects_incompatible_vectors(values: Any) -> None:
    with pytest.raises(RuntimeError):
        embedding_service._validated_embedding(values)


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
    ) -> list[float]:
        if text == "fails":
            await sibling_started.wait()
            raise RuntimeError("provider failure")
        sibling_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            sibling_cancelled.set()
        return [0.1] * embedding_service.EMBEDDING_DIMENSIONS

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
