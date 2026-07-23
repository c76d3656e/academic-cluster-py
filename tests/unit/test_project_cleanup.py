"""Project deletion coordinates task cancellation and checkpoint erasure."""

from contextlib import asynccontextmanager
from typing import Any

import pytest

from academic_cluster.services.project_cleanup import delete_project_data


class _Manager:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def begin_project_deletion(self, project_id: str) -> None:
        self.events.append(f"begin:{project_id}")

    async def end_project_deletion(self, project_id: str) -> None:
        self.events.append(f"end:{project_id}")


class _Session:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        del params
        sql = " ".join(str(statement).split())
        self.events.append(sql)
        if self.fail:
            raise RuntimeError("delete failed")


class _Database:
    def __init__(self, events: list[str], *, fail: bool = False) -> None:
        self.events = events
        self.fail = fail

    @asynccontextmanager
    async def session(self):
        yield _Session(self.events, fail=self.fail)


async def test_project_cleanup_stops_runtime_and_deletes_checkpoints_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    manager = _Manager(events)

    async def delete_checkpoints(project_id: str) -> int:
        events.append(f"checkpoints:{project_id}")
        return 2

    monkeypatch.setattr(
        "academic_cluster.services.agent_runtime.get_agent_run_manager",
        lambda: manager,
    )
    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.delete_project_checkpoints",
        delete_checkpoints,
    )

    await delete_project_data("project-1", _Database(events))

    assert events[:2] == ["begin:project-1", "checkpoints:project-1"]
    assert any("DELETE FROM llm_calls" in event for event in events)
    assert any("DELETE FROM projects WHERE id" in event for event in events)
    assert events[-1] == "end:project-1"


async def test_project_cleanup_releases_start_barrier_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    manager = _Manager(events)

    async def delete_checkpoints(project_id: str) -> int:
        events.append(f"checkpoints:{project_id}")
        return 0

    monkeypatch.setattr(
        "academic_cluster.services.agent_runtime.get_agent_run_manager",
        lambda: manager,
    )
    monkeypatch.setattr(
        "academic_cluster.agents.checkpoint.delete_project_checkpoints",
        delete_checkpoints,
    )

    with pytest.raises(RuntimeError, match="delete failed"):
        await delete_project_data("project-1", _Database(events, fail=True))

    assert events[-1] == "end:project-1"
