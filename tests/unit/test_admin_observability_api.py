"""Admin provider, audit and global usage response contracts."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import HTTPException

from academic_cluster.api.admin import audit, providers, usage


class _Result:
    def __init__(
        self,
        *,
        row: tuple[Any, ...] | None = None,
        rows: list[tuple[Any, ...]] | None = None,
        scalar: int | None = None,
    ) -> None:
        self._row = row
        self._rows = rows or []
        self._scalar = scalar

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows

    def scalar(self) -> int | None:
        return self._scalar


class _Session:
    def __init__(self, results: list[_Result]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(
        self,
        statement: Any,
        params: dict[str, Any] | None = None,
    ) -> _Result:
        self.calls.append((str(statement), params or {}))
        return self.results.pop(0)


class _Database:
    def __init__(self, results: list[_Result]) -> None:
        self.session_instance = _Session(results)
        self.activities: list[dict[str, Any]] = []

    @asynccontextmanager
    async def session(self):  # type: ignore[no-untyped-def]
        yield self.session_instance

    async def log_activity(self, **values: Any) -> str:
        self.activities.append(values)
        return "activity-1"


@pytest.mark.asyncio
async def test_delete_provider_reloads_runtime_and_records_admin_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _Database([_Result(row=("provider-1", "embedding", "Primary embeddings"))])
    reloads = 0

    async def reload_runtime() -> int:
        nonlocal reloads
        reloads += 1
        return 3

    monkeypatch.setattr(providers, "_reload_runtime_pools", reload_runtime)

    response = await providers.delete_provider(
        "provider-1",
        admin={"id": "admin-1"},
        db=db,  # type: ignore[arg-type]
    )

    assert response.model_dump() == {
        "id": "provider-1",
        "kind": "embedding",
        "display_name": "Primary embeddings",
        "reloaded": 3,
        "message": "删除成功",
    }
    assert reloads == 1
    assert "RETURNING id, kind, display_name" in db.session_instance.calls[0][0]
    assert db.activities == [
        {
            "user_id": "admin-1",
            "action": "provider.delete",
            "resource_type": "provider",
            "resource_id": "provider-1",
            "details": {
                "kind": "embedding",
                "display_name": "Primary embeddings",
            },
        }
    ]


@pytest.mark.asyncio
async def test_delete_provider_returns_not_found_without_reloading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _Database([_Result(row=None)])

    async def should_not_reload() -> int:
        pytest.fail("missing provider must not trigger a pool reload")

    monkeypatch.setattr(providers, "_reload_runtime_pools", should_not_reload)

    with pytest.raises(HTTPException) as caught:
        await providers.delete_provider(
            "missing",
            admin={"id": "admin-1"},
            db=db,  # type: ignore[arg-type]
        )

    assert caught.value.status_code == 404
    assert db.activities == []


@pytest.mark.asyncio
async def test_audit_logs_include_email_from_users_join() -> None:
    db = _Database(
        [
            _Result(scalar=1),
            _Result(
                rows=[
                    (
                        "activity-1",
                        "user-1",
                        "project.create",
                        "project",
                        "project-1",
                        '{"query": "graph learning"}',
                        "127.0.0.1",
                        "2026-07-18T10:00:00+00:00",
                        "researcher@example.com",
                    )
                ]
            ),
        ]
    )

    response = await audit.get_audit_logs(
        admin={"id": "admin-1"},
        db=db,  # type: ignore[arg-type]
    )

    assert response.total == 1
    assert response.logs[0].user_email == "researcher@example.com"
    assert response.logs[0].details == {"query": "graph learning"}
    assert "LEFT JOIN users u ON u.id = ua.user_id" in (db.session_instance.calls[1][0])


@pytest.mark.asyncio
async def test_global_recent_calls_returns_embedding_records_by_default() -> None:
    row = (
        "call-1",
        "run-1",
        "project-1",
        "Graph survey",
        "user-1",
        "researcher@example.com",
        "node-execution-1",
        "analysis",
        "embedding-primary",
        "text-embedding-3-small",
        "text-embedding-3-small",
        "openai/text-embedding-3-small",
        "embedding",
        "success",
        "running",
        None,
        200,
        42,
        0,
        42,
        0.000001,
        0.02,
        0.0,
        14.0,
        "paper title and abstract",
        None,
        {"input_count": 1},
        "2026-07-18T10:00:00+00:00",
    )
    db = _Database([_Result(rows=[row])])

    response = await usage.get_recent_calls(
        admin={"id": "admin-1"},
        db=db,  # type: ignore[arg-type]
    )

    assert len(response) == 1
    assert response[0].call_type == "embedding"
    assert response[0].user_email == "researcher@example.com"
    sql = db.session_instance.calls[0][0]
    assert "FROM llm_calls lc" in sql
    assert "call_type = 'llm'" not in sql


@pytest.mark.asyncio
async def test_global_recent_calls_accepts_type_filter_and_offset() -> None:
    db = _Database([_Result(rows=[])])

    response = await usage.get_recent_calls(
        limit=20,
        skip=40,
        call_type="llm",
        status="error",
        admin={"id": "admin-1"},
        db=db,  # type: ignore[arg-type]
    )

    assert response == []
    sql, params = db.session_instance.calls[0]
    assert "lc.call_type = :call_type" in sql
    assert "lc.status = :status" in sql
    assert "OFFSET :skip" in sql
    assert params == {
        "limit": 20,
        "skip": 40,
        "call_type": "llm",
        "status": "error",
    }
