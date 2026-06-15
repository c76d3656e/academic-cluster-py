import pytest

from academic_cluster.agents.evidence_generation import (
    fallback_missing_card,
    generate_evidence_cards_batch,
    normalize_evidence_card,
)
from academic_cluster.graphs.nodes.evidence_cards import _select_evidence_paper_ids
from academic_cluster.graphs.state import PipelineState


def test_normalize_evidence_card_preserves_real_paper_identity_and_metadata():
    paper = {
        "id": "paper-1",
        "title": "Real Paper Title",
        "abstract": "A useful abstract.",
        "publication_date": "2024-05-01",
        "authors": [{"name": "Alice"}],
    }
    raw = {
        "paper_id": "wrong-id",
        "title": "Model Title",
        "claim": "  Important finding.  ",
        "evidence_span": "  Evidence sentence.  ",
        "method": " Method ",
        "confidence": 2.5,
    }

    card = normalize_evidence_card(raw, paper)

    assert card["paper_id"] == "paper-1"
    assert card["title"] == "Real Paper Title"
    assert card["year"] == 2024
    assert card["claim"] == "Important finding."
    assert card["evidence_span"] == "Evidence sentence."
    assert card["confidence"] == 1.0


def test_missing_or_unusable_evidence_card_uses_slot_fallback():
    paper = {
        "id": "paper-2",
        "title": "Fallback Title",
        "abstract": "Fallback abstract with usable evidence.",
    }

    card = normalize_evidence_card({"claim": "", "evidence_span": ""}, paper)

    assert card == fallback_missing_card(paper)
    assert card["paper_id"] == "paper-2"
    assert card["source_api"] == "fallback_missing_card"
    assert card["confidence"] == 0.05


@pytest.mark.asyncio
async def test_generate_evidence_cards_batch_keeps_one_card_per_paper(monkeypatch):
    papers = [
        {"id": "paper-1", "title": "Paper 1", "abstract": "Abstract 1"},
        {"id": "paper-2", "title": "Paper 2", "abstract": "Abstract 2"},
    ]

    async def fake_generate_evidence_card(paper, cluster_topics=None):
        if paper["id"] == "paper-2":
            raise RuntimeError("model failed")
        return {
            "paper_id": "wrong",
            "claim": "Claim 1",
            "evidence_span": "Evidence 1",
            "confidence": 0.8,
        }

    monkeypatch.setattr(
        "academic_cluster.agents.evidence_generation.generate_evidence_card",
        fake_generate_evidence_card,
    )

    cards = await generate_evidence_cards_batch(papers)

    assert [card["paper_id"] for card in cards] == ["paper-1", "paper-2"]
    assert cards[0]["source_api"] == "llm"
    assert cards[1]["source_api"] == "fallback_missing_card"


def test_select_evidence_paper_ids_uses_core_only():
    state = PipelineState(
        project_id="project-1",
        query="topic",
        core_paper_ids=[f"core-{i}" for i in range(160)],
        auxiliary_paper_ids=[f"aux-{i}" for i in range(160)],
        reranked_paper_ids=[f"reranked-{i}" for i in range(200)],
    )

    selected = _select_evidence_paper_ids(state)

    assert len(selected) == 160
    assert selected == [f"core-{i}" for i in range(160)]


def test_select_evidence_paper_ids_deduplicates_and_never_uses_auxiliary_or_reranked():
    state = PipelineState(
        project_id="project-1",
        query="topic",
        core_paper_ids=["core-1", "core-1", "core-2"],
        auxiliary_paper_ids=["aux-1"],
        reranked_paper_ids=["reranked-1"],
    )

    selected = _select_evidence_paper_ids(state)

    assert selected == ["core-1", "core-2"]
