"""Writing-stage grounding, citation, and finalization invariants."""

from typing import Any

import pytest

from academic_cluster.agents import agent_graph


def _state() -> agent_graph.AgentState:
    return agent_graph.AgentState(
        project_id="project-1",
        execution_id="execution-1",
        topic="Autonomous agents",
        target_words=1000,
        papers=[
            {"id": "p1", "title": "Foundations", "abstract": "Planning basics"},
            {"id": "p2", "title": "Tools", "abstract": "Agent tool evidence"},
            {"id": "p3", "title": "Unused", "abstract": "Unrelated hardware"},
        ],
        evidence_cards=[
            {"paper_id": "p2", "claim": "Tool use improves task completion."}
        ],
        research_complete=True,
        analysis_complete=True,
    )


def test_section_sources_preserve_global_numbers_and_include_evidence() -> None:
    state = _state()
    references = agent_graph.build_reference_map(state.papers)

    sources = agent_graph._build_section_sources(
        {"title": "Agent tools", "key_points": ["tool use"]},
        references,
        state.papers,
        state.evidence_cards,
        preferred_paper_ids=["p2"],
    )

    assert [source["paper_id"] for source in sources] == ["p2"]
    assert sources[0]["number"] == 2
    assert sources[0]["abstract"] == "Agent tool evidence"
    assert sources[0]["evidence_claims"] == ["Tool use improves task completion."]


def test_section_source_ranking_does_not_mutate_shared_reference_map() -> None:
    state = _state()
    references = agent_graph.build_reference_map(state.papers)
    original_order = [reference["paper_id"] for reference in references]

    sources = agent_graph._build_section_sources(
        {"title": "Agent tools", "key_points": ["tool use"]},
        references,
        state.papers,
        state.evidence_cards,
    )

    assert sources[0]["paper_id"] == "p2"
    assert [reference["paper_id"] for reference in references] == original_order


def test_review_body_minimum_allows_five_percent_tolerance() -> None:
    assert agent_graph._minimum_review_word_units(12000) == 4560
    assert agent_graph._minimum_review_word_units(1000) == 380


@pytest.mark.asyncio
async def test_writing_renumbers_by_first_use_and_drops_uncited_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_writing(**_kwargs: Any) -> dict[str, Any]:
        return {
            "outline": {
                "title": "Agent Survey",
                "sections": [{"title": "Tools"}, {"title": "Foundations"}],
            }
        }

    async def fake_sections(
        _state: agent_graph.AgentState,
        _outline: dict[str, Any],
        _references: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "section_id": "1",
                "title": "Tools",
                "content": "Tool evidence " + ("is well supported " * 80) + "[2].",
                "allowed_reference_numbers": [2],
            },
            {
                "section_id": "2",
                "title": "Foundations",
                "content": "Earlier work "
                + ("establishes the baseline " * 80)
                + "[1].",
                "allowed_reference_numbers": [1],
            },
        ]

    async def no_persist(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        "academic_cluster.agents.writing_team.run_writing",
        fake_run_writing,
    )
    monkeypatch.setattr(agent_graph, "_write_new_sections", fake_sections)
    monkeypatch.setattr(agent_graph, "_persist_writing_artifacts", no_persist)

    result = await agent_graph._writing_node(_state())

    assert result["status"] == "running"
    assert [reference["paper_id"] for reference in result["final_references"]] == [
        "p2",
        "p1",
    ]
    assert [reference["new_number"] for reference in result["final_references"]] == [
        1,
        2,
    ]
    assert "[1]" in result["sections"][0]["content"]
    assert "[2]" in result["sections"][1]["content"]
    assert "Unused" not in result["final_review"]


@pytest.mark.asyncio
async def test_final_review_numbering_uses_abstract_first_appearance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_writing(**_kwargs: Any) -> dict[str, Any]:
        return {
            "outline": {
                "title": "Agent Survey",
                "sections": [{"title": "One"}, {"title": "Two"}],
            }
        }

    async def fake_sections(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "section_id": "1",
                "title": "One",
                "content": "Opening [1]. "
                + ("source evidence " * 60)
                + "\n\n"
                + ("Later source " * 80)
                + "[2].",
                "allowed_reference_numbers": [1, 2],
            },
            {
                "section_id": "2",
                "title": "Two",
                "content": "Second [3]. " + ("opening evidence " * 70),
                "allowed_reference_numbers": [3],
            },
        ]

    async def no_persist(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(
        "academic_cluster.agents.writing_team.run_writing", fake_run_writing
    )
    monkeypatch.setattr(agent_graph, "_write_new_sections", fake_sections)
    monkeypatch.setattr(agent_graph, "_persist_writing_artifacts", no_persist)
    state = _state().model_copy(
        update={
            "papers": [
                {"id": "p1", "title": "One"},
                {"id": "p2", "title": "Two"},
                {"id": "p3", "title": "Three"},
            ]
        }
    )

    result = await agent_graph._writing_node(state)
    body = result["final_review"].split("## References", 1)[0]

    # The abstract contains section 1's first citation and then section 2's,
    # so the later citation in section 1 must receive number 3.
    assert "Later source " in body
    assert [mapping["original_number"] for mapping in result["final_references"]] == [
        1,
        3,
        2,
    ]
    assert "[3]." in result["sections"][0]["content"]


@pytest.mark.asyncio
async def test_revision_remaps_feedback_and_cleans_model_commentary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []

    class _RevisionTool:
        async def ainvoke(self, inputs: dict[str, Any]) -> str:
            captured.append(inputs)
            return (
                "<think>hidden reasoning</think>\n"
                "（本次修改严格遵循用户规则，不新增引用。）\n"
                + str(inputs["section_text"])
            )

    monkeypatch.setattr(
        "academic_cluster.tools.agent_tools.revise_section", _RevisionTool()
    )
    state = _state().model_copy(
        update={
            "revision_feedback": "Replace weak evidence at [1].",
            "sections": [
                {
                    "section_id": "s1",
                    "title": "Section",
                    "content": ("supported content " * 20) + "[1].",
                    "allowed_reference_numbers": [7],
                }
            ],
            "final_references": [{"new_number": 1, "original_number": 7}],
        }
    )

    sections = await agent_graph._revise_sections(state)

    assert "[7]" in captured[0]["section_text"]
    assert "[7]" in captured[0]["revision_instructions"]
    assert "<think>" not in sections[0]["content"]
    assert "本次修改" not in sections[0]["content"]


@pytest.mark.asyncio
async def test_writing_rejects_citation_outside_section_evidence_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_writing(**_kwargs: Any) -> dict[str, Any]:
        return {"outline": {"title": "Survey", "sections": [{"title": "Body"}]}}

    async def fake_sections(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "section_id": "1",
                "title": "Body",
                "content": ("unsupported citation " * 30) + "[1].",
                "allowed_reference_numbers": [2],
            }
        ]

    monkeypatch.setattr(
        "academic_cluster.agents.writing_team.run_writing", fake_run_writing
    )
    monkeypatch.setattr(agent_graph, "_write_new_sections", fake_sections)

    result = await agent_graph._writing_node(_state())

    assert result["status"] == "writing_failed"
    assert "outside its evidence plan" in result["warnings"][0]


@pytest.mark.asyncio
async def test_writing_rejects_total_output_far_below_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_writing(**_kwargs: Any) -> dict[str, Any]:
        return {"outline": {"title": "Survey", "sections": [{"title": "Body"}]}}

    async def fake_sections(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "section_id": "1",
                "title": "Body",
                "content": ("short but cited " * 10) + "[1].",
                "allowed_reference_numbers": [1],
            }
        ]

    monkeypatch.setattr(
        "academic_cluster.agents.writing_team.run_writing", fake_run_writing
    )
    monkeypatch.setattr(agent_graph, "_write_new_sections", fake_sections)
    state = _state().model_copy(update={"target_words": 12000})

    result = await agent_graph._writing_node(state)

    assert result["status"] == "writing_failed"
    assert "below required minimum" in result["warnings"][0]


@pytest.mark.asyncio
async def test_reference_list_cannot_make_uncited_body_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run_writing(**_kwargs: Any) -> dict[str, Any]:
        return {"outline": {"title": "Survey", "sections": [{"title": "Body"}]}}

    async def fake_sections(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "section_id": "1",
                "title": "Body",
                "content": "This unsupported prose is deliberately long. " * 5,
            }
        ]

    monkeypatch.setattr(
        "academic_cluster.agents.writing_team.run_writing",
        fake_run_writing,
    )
    monkeypatch.setattr(agent_graph, "_write_new_sections", fake_sections)

    result = await agent_graph._writing_node(_state())

    assert result["status"] == "writing_failed"
    assert result["failed_phase"] == "writing"
