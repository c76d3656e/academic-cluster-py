"""Contract tests for user-console API responses."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest

from academic_cluster.api.console.dashboard import get_dashboard_overview


class _Result:
    def __init__(
        self,
        *,
        scalar: int | None = None,
        row: tuple[Any, ...] | None = None,
        rows: list[tuple[Any, ...]] | None = None,
    ) -> None:
        self._scalar = scalar
        self._row = row
        self._rows = rows or []

    def scalar(self) -> int | None:
        return self._scalar

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._row

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _DashboardSession:
    def __init__(self) -> None:
        created_at = datetime(2026, 7, 18, tzinfo=UTC)
        self.results = iter(
            [
                _Result(scalar=2),
                _Result(scalar=1),
                _Result(scalar=12),
                _Result(row=(1200, 0.25)),
                _Result(
                    rows=[
                        (
                            "project-1",
                            "Active project",
                            "running:agent:writing",
                            created_at,
                        ),
                        ("project-2", "New project", "created", created_at),
                    ]
                ),
            ]
        )

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        del statement, params
        return next(self.results)


class _DashboardDatabase:
    @asynccontextmanager
    async def session(self):  # type: ignore[no-untyped-def]
        yield _DashboardSession()


@pytest.mark.asyncio
async def test_console_recent_projects_use_canonical_public_statuses() -> None:
    response = await get_dashboard_overview(
        current_user={"id": "user-1", "role": "user"},
        db=_DashboardDatabase(),  # type: ignore[arg-type]
    )

    assert response.project_count == 2
    assert response.running_projects == 1
    assert [project.status for project in response.recent_projects] == [
        "running",
        "pending",
    ]
