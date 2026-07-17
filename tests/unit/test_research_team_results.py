"""Research completion is accepted only from a successful finalize tool call."""

from __future__ import annotations

import json
from typing import Any

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from academic_cluster.agents import research_team


class _Agent:
    def __init__(self, messages: list[Any]) -> None:
        self.messages = messages
        self.calls: list[tuple[dict[str, Any], dict[str, Any]]] = []

    async def ainvoke(
        self,
        payload: dict[str, Any],
        *,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self.calls.append((payload, config))
        return {"messages": self.messages}


class _Database:
    def __init__(self, papers: list[dict[str, Any]]) -> None:
        self.papers = papers
        self.calls: list[tuple[str, int]] = []

    async def get_project_papers(
        self,
        project_id: str,
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        self.calls.append((project_id, limit))
        return self.papers


def _finalize_messages(
    *,
    status: str = "success",
    total: object = 2,
) -> list[Any]:
    call_id = "finalize-1"
    return [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "finalize_research",
                    "args": {
                        "summary_json": json.dumps(
                            {
                                "total": total,
                                "coverage_assessment": "broad coverage",
                            }
                        ),
                        "total_papers": total,
                        "queries_used": "query one, query two",
                    },
                    "id": call_id,
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(
            content=json.dumps({"status": "research_complete"}),
            tool_call_id=call_id,
            status=status,  # type: ignore[arg-type]
        ),
    ]


@pytest.mark.asyncio
async def test_run_research_requires_successful_finalize_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _Agent(_finalize_messages(status="error"))
    database = _Database([])
    monkeypatch.setattr(research_team, "create_research_agent", lambda **_kw: agent)
    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: database,
    )

    with pytest.raises(RuntimeError, match="without finalizing"):
        await research_team.run_research(
            "agent safety",
            "project-1",
            target_papers=5,
        )


@pytest.mark.asyncio
async def test_run_research_parses_success_and_deduplicates_project_papers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _Agent(_finalize_messages(total="not-a-number"))
    database = _Database(
        [
            {"id": "paper-1", "title": "One"},
            {"paper_id": "paper-1", "title": "Duplicate"},
            {"paper_id": "paper-2", "title": "Two"},
            {"title": "Missing identifier"},
        ]
    )
    monkeypatch.setattr(research_team, "create_research_agent", lambda **_kw: agent)
    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: database,
    )

    result = await research_team.run_research(
        "agent safety",
        "project-1",
        target_papers=999,
        supplemental_queries=["tool failure", "checkpoint recovery"],
    )

    assert [paper["id"] for paper in result["papers"]] == ["paper-1", "paper-2"]
    assert result["total_found"] == 2
    assert result["relevant_count"] == 2
    assert result["coverage_assessment"] == "broad coverage"
    assert result["queries_used"] == "query one, query two"
    assert database.calls == [("project-1", 500)]
    payload, config = agent.calls[0]
    assert config == {"recursion_limit": 18}
    prompt = str(payload["messages"][0].content)
    assert "tool failure" in prompt
    assert "checkpoint recovery" in prompt
