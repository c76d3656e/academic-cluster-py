"""Concurrent Agent context must never leak across projects."""

import asyncio

import pytest

from academic_cluster.services.observability import (
    get_current_agent_phase,
    get_current_execution,
    get_current_project,
    pop_current_agent_phase,
    pop_current_execution,
    pop_current_project,
    push_current_agent_phase,
    push_current_execution,
    push_current_project,
)


@pytest.mark.asyncio
async def test_project_and_execution_context_are_task_local() -> None:
    ready = 0
    ready_lock = asyncio.Lock()
    release = asyncio.Event()

    async def worker(
        project_id: str, execution_id: str, phase: str
    ) -> tuple[str | None, str | None, str | None]:
        nonlocal ready
        project_token = push_current_project(project_id)
        execution_token = push_current_execution(execution_id)
        phase_token = push_current_agent_phase(phase)
        try:
            async with ready_lock:
                ready += 1
                if ready == 2:
                    release.set()
            await release.wait()
            await asyncio.sleep(0)
            return (
                get_current_project(),
                get_current_execution(),
                get_current_agent_phase(),
            )
        finally:
            pop_current_agent_phase(phase_token)
            pop_current_execution(execution_token)
            pop_current_project(project_token)

    first, second = await asyncio.gather(
        worker("project-a", "execution-a", "research"),
        worker("project-b", "execution-b", "writing"),
    )

    assert first == ("project-a", "execution-a", "research")
    assert second == ("project-b", "execution-b", "writing")
    assert get_current_project() is None
    assert get_current_execution() is None
    assert get_current_agent_phase() is None
