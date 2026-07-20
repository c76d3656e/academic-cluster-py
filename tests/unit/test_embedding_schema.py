"""Embedding schema migration contracts."""

from contextlib import asynccontextmanager
from typing import Any

from academic_cluster.api.main import _ensure_embedding_schema


class _Session:
    def __init__(self) -> None:
        self.statements: list[str] = []

    async def execute(self, statement: Any) -> None:
        self.statements.append(str(statement))


class _Database:
    def __init__(self) -> None:
        self.opened_session = _Session()

    @asynccontextmanager
    async def session(self):
        yield self.opened_session


async def test_embedding_schema_allows_high_dimensions_with_exact_lookup() -> None:
    database = _Database()

    await _ensure_embedding_schema(database)

    sql = "\n".join(database.opened_session.statements)
    assert "ALTER TABLE embeddings ALTER COLUMN vector TYPE vector" in sql
    assert "ALTER TABLE embeddings ADD COLUMN IF NOT EXISTS dimensions INTEGER" in sql
    assert "UPDATE embeddings SET dimensions = vector_dims(vector)" in sql
    assert "DROP INDEX IF EXISTS idx_embeddings_vector" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_embeddings_lookup" in sql
    assert "ON embeddings (model_name, dimensions, paper_id)" in sql
