import pytest

from academic_cluster.agents import writing
from academic_cluster.agents.section_outline import _normalize_paragraph_word_budget
from academic_cluster.graphs.nodes.write_review import _section_citation_payload
from academic_cluster.services.citation_planner import SectionCitationPlan


def test_section_citation_payload_includes_candidate_paper_details():
    plan = SectionCitationPlan(
        section_index=0,
        section_title="Methods",
        key_clusters=[2],
        candidate_paper_ids=["paper-a", "paper-b"],
        candidate_details=[
            {
                "paper_id": "paper-a",
                "cluster_id": 2,
                "is_core": True,
                "source": "community_core",
            },
            {
                "paper_id": "paper-b",
                "cluster_id": 3,
                "is_core": False,
                "source": "global_auxiliary",
            },
        ],
    )
    paper_map = {
        "paper-a": {
            "id": "paper-a",
            "title": "Core Paper",
            "abstract": "Core abstract",
            "publication_date": "2024-01-01",
            "journal": "Journal A",
        },
        "paper-b": {
            "id": "paper-b",
            "title": "Auxiliary Paper",
            "abstract": "Auxiliary abstract",
            "year": 2023,
            "venue": "Venue B",
        },
    }

    payload = _section_citation_payload(plan, paper_map)

    assert payload["candidate_paper_ids"] == ["paper-a", "paper-b"]
    # id/paper_id 使用局部编号（整数索引），方便文内引用 [1], [2]
    assert [paper["id"] for paper in payload["papers"]] == [1, 2]
    assert [paper["paper_id"] for paper in payload["papers"]] == [1, 2]
    assert payload["papers"][0]["local_number"] == 1
    assert payload["papers"][0]["title"] == "Core Paper"
    assert payload["papers"][0]["year"] == "2024"
    assert payload["papers"][0]["source"] == "community_core"
    assert payload["papers"][1]["is_core"] is False


@pytest.mark.asyncio
async def test_write_section_units_single_call(monkeypatch):
    calls = []

    async def fake_write_section(**kwargs):
        calls.append(kwargs["section_outline"])
        return "Section body with citations [1,2,3]"

    monkeypatch.setattr(writing, "write_section", fake_write_section)
    monkeypatch.delenv("WRITING_REFINE_SECTION_UNITS", raising=False)

    outline = {
        "core_question": "q",
        "narrative_arc": "arc",
        "paragraphs": [
            {
                "index": 1,
                "task_type": "context",
                "direction": "a",
                "target_words": 300,
                "synthesis_instruction": "x",
            },
            {
                "index": 2,
                "task_type": "comparison",
                "direction": "b",
                "target_words": 300,
                "synthesis_instruction": "y",
            },
            {
                "index": 3,
                "task_type": "limitation",
                "direction": "c",
                "target_words": 300,
                "synthesis_instruction": "z",
            },
        ],
    }

    result = await writing.write_section_units(
        topic="topic",
        review_title="title",
        section_plan={"title": "sec", "description": "desc", "target_words": 900},
        cluster_data="cluster",
        sample_papers="samples",
        references="[1] x",
        evidence_cards=[],
        section_outline=outline,
    )

    assert len(calls) == 1
    assert calls[0] is outline
    assert result == "Section body with citations [1,2,3]"


def test_normalize_paragraph_word_budget_keeps_section_total():
    outline = {
        "paragraphs": [
            {"index": 1, "target_words": 300},
            {"index": 2, "target_words": 600},
            {"index": 3, "target_words": 900},
        ],
    }

    normalized = _normalize_paragraph_word_budget(outline, target_words=1200)
    targets = [paragraph["target_words"] for paragraph in normalized["paragraphs"]]

    assert sum(targets) == 1200
    assert targets[0] < targets[1] < targets[2]


def test_writing_prompt_budget_compacts_large_context():
    large = "x" * 80000

    compact = writing._clip_text_block(large, 1000)
    max_tokens = writing._writing_max_tokens_for_prompt(large, requested=8192)

    assert len(compact) < 1200
    assert "truncated for context budget" in compact
    assert 1024 <= max_tokens < 8192
