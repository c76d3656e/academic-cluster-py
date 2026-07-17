"""Project-scoped search persistence and tool-audit tests."""

import json
from typing import Any

import pytest

from academic_cluster.services.observability import (
    pop_current_execution,
    pop_current_project,
    push_current_execution,
    push_current_project,
)
from academic_cluster.tools import agent_tools


class _FakeDatabase:
    def __init__(self, newly_linked: int = 1) -> None:
        self.links: list[dict[str, Any]] = []
        self.audits: list[dict[str, Any]] = []
        self.evidence_cards: list[dict[str, Any]] = []
        self.saved_evidence_cards: list[dict[str, Any]] = []
        self.newly_linked = newly_linked

    async def save_paper(self, paper: dict[str, Any]) -> str:
        return str(paper["id"])

    async def link_project_papers(
        self,
        project_id: str,
        paper_ids: list[str],
        *,
        execution_id: str,
        source_query: str,
    ) -> int:
        self.links.append(
            {
                "project_id": project_id,
                "paper_ids": paper_ids,
                "execution_id": execution_id,
                "source_query": source_query,
            }
        )
        return self.newly_linked

    async def record_agent_tool_call(self, **kwargs: Any) -> str:
        self.audits.append(kwargs)
        return "audit-1"

    async def get_project_evidence_cards(
        self,
        project_id: str,
        *,
        paper_ids: list[str],
    ) -> list[dict[str, Any]]:
        assert project_id == "project-1"
        return [
            card
            for card in self.evidence_cards
            if str(card.get("paper_id")) in paper_ids
        ]

    async def save_evidence_card(self, card: dict[str, Any]) -> str:
        self.saved_evidence_cards.append(card)
        return "evidence-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("newly_linked", [0, 1])
async def test_search_links_only_current_project_and_records_audit(
    monkeypatch: pytest.MonkeyPatch,
    newly_linked: int,
) -> None:
    database = _FakeDatabase(newly_linked)

    async def fake_search(**kwargs: Any) -> list[dict[str, Any]]:
        assert kwargs["limit_per_source"] == 20
        return [
            {"id": "paper-1", "title": "Scoped paper", "year": 2025},
            {"id": "paper-1-copy", "title": "Scoped paper", "year": 2025},
        ]

    monkeypatch.setattr(
        "academic_cluster.tools.academic_search.search_all_sources",
        fake_search,
    )
    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: database,
    )
    project_token = push_current_project("project-1")
    execution_token = push_current_execution("execution-1")
    try:
        raw = await agent_tools.search_papers.ainvoke(
            {"query": "agents", "limit_per_source": 1000}
        )
    finally:
        pop_current_execution(execution_token)
        pop_current_project(project_token)

    summary = json.loads(raw)
    assert summary["paper_ids_count"] == 1
    assert summary["unique_saved"] == newly_linked
    assert database.links == [
        {
            "project_id": "project-1",
            "paper_ids": ["paper-1"],
            "execution_id": "execution-1",
            "source_query": "agents",
        }
    ]
    assert len(database.audits) == 1
    assert database.audits[0]["project_id"] == "project-1"
    assert database.audits[0]["execution_id"] == "execution-1"
    assert database.audits[0]["tool_name"] == "search_papers"
    assert database.audits[0]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_transient_fallback_evidence_is_not_persisted_or_reused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = _FakeDatabase()
    database.evidence_cards = [
        {
            "paper_id": "paper-1",
            "claim": "legacy placeholder",
            "confidence": 0.05,
            "limitation": (
                "LLM evidence card extraction did not return a usable card for "
                "this paper."
            ),
        }
    ]

    async def fake_generate(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "paper_id": "paper-1",
                "claim": "temporary placeholder",
                "source_api": "fallback_missing_card",
                "confidence": 0.05,
            }
        ]

    monkeypatch.setattr(
        "academic_cluster.agents.evidence_generation.generate_evidence_cards_batch",
        fake_generate,
    )
    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: database,
    )
    project_token = push_current_project("project-1")
    execution_token = push_current_execution("execution-1")
    try:
        raw = await agent_tools.generate_evidence.ainvoke(
            {
                "papers_json": json.dumps(
                    [{"id": "paper-1", "title": "Fallback paper"}]
                ),
                "topic": "agents",
            }
        )
    finally:
        pop_current_execution(execution_token)
        pop_current_project(project_token)

    result = json.loads(raw)
    assert result["fallback_count"] == 1
    assert result["evidence_cards"] == []
    assert database.saved_evidence_cards == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "reported_output",
    [json.dumps({"error": "coverage failed"}), {"error": "coverage failed"}],
)
async def test_structured_tool_error_is_audited_as_failed(
    monkeypatch: pytest.MonkeyPatch,
    reported_output: Any,
) -> None:
    database = _FakeDatabase()

    async def reports_error() -> Any:
        return reported_output

    monkeypatch.setattr(
        "academic_cluster.services.database.get_database",
        lambda: database,
    )
    wrapped = agent_tools._audited_agent_tool("analysis")(reports_error)
    project_token = push_current_project("project-1")
    execution_token = push_current_execution("execution-1")
    try:
        assert await wrapped() == reported_output
    finally:
        pop_current_execution(execution_token)
        pop_current_project(project_token)

    assert len(database.audits) == 1
    assert database.audits[0]["status"] == "failed"
    assert database.audits[0]["error_message"] == "coverage failed"
