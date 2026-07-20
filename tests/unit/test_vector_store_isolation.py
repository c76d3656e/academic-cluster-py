"""Vector neighbors must be selected inside the project paper set."""

from contextlib import asynccontextmanager
from typing import Any

import pytest

from academic_cluster.services.vector_store import VectorStoreService


class _Result:
    def fetchall(self) -> list[tuple[str, str, float]]:
        return [("paper-a", "paper-b", 0.91)]


class _Session:
    def __init__(self) -> None:
        self.statement = ""
        self.params: dict[str, Any] = {}

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        self.statement = str(statement)
        self.params = params
        return _Result()


class _Database:
    def __init__(self) -> None:
        self.opened_session = _Session()

    @asynccontextmanager
    async def session(self):
        yield self.opened_session


async def test_knn_candidates_are_filtered_before_top_k() -> None:
    database = _Database()
    store = object.__new__(VectorStoreService)
    store.db = database

    edges = await store.get_knn_graph(
        ["paper-a", "paper-b"],
        k=3,
        threshold=0.4,
        model_name="embedding-model-v2",
    )

    assert edges == [{"source": "paper-a", "target": "paper-b", "weight": 0.91}]
    assert (
        "paper_id = ANY(CAST(:paper_ids AS uuid[]))"
        in database.opened_session.statement
    )
    assert "FROM project_embeddings AS candidate" in database.opened_session.statement
    assert "AND model_name = :model_name" in database.opened_session.statement
    assert database.opened_session.params == {
        "paper_ids": ["paper-a", "paper-b"],
        "neighbor_count": 3,
            "threshold": 0.4,
            "model_name": "embedding-model-v2",
            "dimensions": None,
        }


async def test_knn_empty_input_does_not_open_database_session() -> None:
    store = object.__new__(VectorStoreService)
    store.db = None

    assert await store.get_knn_graph([], k=3, model_name="embedding-model-v2") == []


async def test_add_embeddings_rejects_mismatched_lengths_before_database() -> None:
    store = object.__new__(VectorStoreService)
    store.db = None

    with pytest.raises(ValueError, match="same number"):
        await store.add_embeddings(
            ["paper-a", "paper-b"],
            [[0.1, 0.2]],
            model_name="embedding-model-v2",
        )
