"""Bounded team wrappers must invoke only the work they own."""

import json
import math
from typing import Any

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from academic_cluster.agents import (
    agent_graph,
    peer_review_team,
    research_team,
    writing_team,
)


class _FakeTool:
    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    async def ainvoke(self, inputs: dict[str, Any]) -> str:
        self.calls.append(inputs)
        return self.output


@pytest.mark.asyncio
async def test_writing_team_calls_outline_operation_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _FakeTool(
        json.dumps(
            {
                "title": "Survey",
                "sections": [
                    {"title": "One"},
                    {"title": "Two"},
                    {"title": "Three"},
                ],
            }
        )
    )
    monkeypatch.setattr(writing_team, "generate_outline", tool)

    result = await writing_team.run_writing("topic", [], target_words=3000)

    assert result["outline"]["title"] == "Survey"
    assert len(tool.calls) == 1


@pytest.mark.asyncio
async def test_peer_review_team_calls_review_operation_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = _FakeTool(
        json.dumps(
            {
                "overall_score": 80,
                "strengths": ["grounded"],
                "weaknesses": [],
                "suggestions": [],
            }
        )
    )
    monkeypatch.setattr(peer_review_team, "peer_review_survey", tool)

    result = await peer_review_team.run_peer_review("review [1]", "topic")

    assert result["review_report"]["overall_score"] == 80
    assert len(tool.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_score", [math.nan, True])
async def test_peer_review_rejects_nonfinite_overall_score(
    monkeypatch: pytest.MonkeyPatch,
    invalid_score: object,
) -> None:
    tool = _FakeTool(
        json.dumps(
            {
                "overall_score": invalid_score,
                "strengths": [],
                "weaknesses": [],
                "suggestions": [],
            }
        )
    )
    monkeypatch.setattr(peer_review_team, "peer_review_survey", tool)

    with pytest.raises(RuntimeError, match="overall_score"):
        await peer_review_team.run_peer_review("review [1]", "topic")


@pytest.mark.asyncio
async def test_graph_quality_gate_defensively_rejects_nonfinite_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_peer_review(**_kwargs: Any) -> dict[str, Any]:
        return {
            "review_report": {
                "overall_score": math.nan,
                "strengths": [],
                "weaknesses": [],
                "suggestions": [],
            }
        }

    monkeypatch.setattr(peer_review_team, "run_peer_review", fake_run_peer_review)
    state = agent_graph.AgentState(
        project_id="project-1",
        execution_id="execution-1",
        topic="topic",
        final_review="supported body [1]",
        writing_complete=True,
    )

    result = await agent_graph._peer_review_node(state)

    assert result["status"] == "peer_review_failed"
    assert result["failed_phase"] == "peer_review"


@pytest.mark.asyncio
async def test_peer_review_chunks_full_long_document_without_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ChunkReviewTool:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        async def ainvoke(self, inputs: dict[str, Any]) -> str:
            self.calls.append(inputs)
            index = len(self.calls)
            return json.dumps(
                {
                    "overall_score": 70 + index,
                    "summary": f"part {index}",
                    "strengths": [f"strength {index}"],
                    "weaknesses": [],
                    "suggestions": [f"suggestion {index}"],
                }
            )

    tool = _ChunkReviewTool()
    monkeypatch.setattr(peer_review_team, "peer_review_survey", tool)
    sentinel = "TAIL_SENTINEL_[9]"
    review = ("evidence-backed paragraph [1].\n\n" * 2200) + sentinel

    result = await peer_review_team.run_peer_review(review, "topic")

    assert len(tool.calls) > 1
    assert any(sentinel in call["review_text"] for call in tool.calls)
    assert all(len(call["review_text"]) < len(review) for call in tool.calls)
    assert result["review_report"]["suggestions"] == [
        f"suggestion {index}" for index in range(1, len(tool.calls) + 1)
    ]


@pytest.mark.asyncio
async def test_research_search_tool_has_a_hard_call_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    search = _FakeTool(json.dumps({"unique_saved": 1}))
    captured: dict[str, Any] = {}

    def fake_create_react_agent(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    class _BindableModel:
        def bind_tools(self, tools: Any, **kwargs: Any) -> "_BindableModel":
            del tools, kwargs
            return self

    monkeypatch.setattr(research_team, "search_papers", search)
    monkeypatch.setattr(research_team, "create_llm", lambda **_kwargs: _BindableModel())
    monkeypatch.setattr(research_team, "create_react_agent", fake_create_react_agent)

    research_team.create_research_agent(max_search_calls=2)
    assert captured["model"].__class__.__name__ == "AuditedChatModel"
    rebound = captured["model"].bind_tools(captured["tools"])
    assert rebound.__class__.__name__ == "AuditedChatModel"
    bounded_search = captured["tools"][0]
    first = await bounded_search.ainvoke({"query": "one", "limit_per_source": 5})
    second = await bounded_search.ainvoke({"query": "two", "limit_per_source": 5})
    exhausted = await bounded_search.ainvoke({"query": "three", "limit_per_source": 5})

    assert json.loads(first)["unique_saved"] == 1
    assert json.loads(second)["unique_saved"] == 1
    assert json.loads(exhausted)["error"] == "search_limit_reached"
    assert len(search.calls) == 2


def test_research_agent_compiles_with_audited_tool_binding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubChatModel(BaseChatModel):
        @property
        def _llm_type(self) -> str:
            return "stub"

        def bind_tools(self, tools: Any, **kwargs: Any) -> "_StubChatModel":
            del tools, kwargs
            return self

        def _generate(
            self,
            messages: list[BaseMessage],
            stop: list[str] | None = None,
            run_manager: Any = None,
            **kwargs: Any,
        ) -> ChatResult:
            del messages, stop, run_manager, kwargs
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content="done"))]
            )

    monkeypatch.setattr(
        research_team,
        "create_llm",
        lambda **_kwargs: _StubChatModel(),
    )

    agent = research_team.create_research_agent(max_search_calls=1)

    assert callable(agent.ainvoke)
