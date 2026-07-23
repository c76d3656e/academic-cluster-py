"""The writing path must consume production UUID clusters without planner errors."""

from __future__ import annotations

import json
from typing import Any

import pytest

from academic_cluster.agents import agent_graph
from academic_cluster.tools import agent_tools


class _WriteTool:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(self, payload: dict[str, Any]) -> str:
        self.calls.append(payload)
        references = json.loads(payload["available_papers_json"])
        citations = " ".join(f"[{reference['number']}]" for reference in references)
        return ("Grounded evidence supports this section. " * 5) + citations


@pytest.mark.asyncio
async def test_write_new_sections_integrates_uuid_cluster_citation_plans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    papers = [
        {
            "id": f"paper-{index}",
            "title": f"Agent topic {index}",
            "abstract": f"Evidence for agent topic {index}.",
        }
        for index in range(4)
    ]
    state = agent_graph.AgentState(
        project_id="project-1",
        execution_id="execution-1",
        topic="agent systems",
        papers=papers,
        coverage={
            "clusters": [
                {
                    "id": "11111111-1111-1111-1111-111111111111",
                    "paper_ids": ["paper-0", "paper-1"],
                },
                {
                    "id": "22222222-2222-2222-2222-222222222222",
                    "paper_ids": ["paper-2", "paper-3"],
                },
            ]
        },
        evidence_cards=[
            {
                "id": f"card-{index}",
                "paper_id": f"paper-{index}",
                "claim": f"Agent topic {index} is supported.",
                "evidence_span": f"Evidence {index}.",
                "confidence": 0.9,
            }
            for index in range(4)
        ],
    )
    outline = {
        "sections": [
            {"id": "planning", "title": "Agent planning"},
            {"id": "tools", "title": "Agent tools"},
        ]
    }
    write_tool = _WriteTool()
    monkeypatch.setattr(agent_tools, "write_section", write_tool)

    sections = await agent_graph._write_new_sections(
        state,
        outline,
        agent_graph.build_reference_map(papers),
    )

    assert [section["section_id"] for section in sections] == ["planning", "tools"]
    assert len(write_tool.calls) == 2
    assert all(section["allowed_reference_numbers"] for section in sections)
    assert all("[1]" in section["content"] for section in sections)
