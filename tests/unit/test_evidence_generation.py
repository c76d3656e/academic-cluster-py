import asyncio

import pytest

from academic_cluster.agents.evidence_generation import generate_evidence_cards_batch


@pytest.mark.asyncio
async def test_generate_evidence_cards_batch_falls_back_on_timeout(monkeypatch):
    async def fake_generate_evidence_card(*args, **kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(
        "academic_cluster.agents.evidence_generation.generate_evidence_card",
        fake_generate_evidence_card,
    )

    papers = [
        {"id": "p1", "title": "Paper 1", "abstract": "Abstract 1"},
        {"id": "p2", "title": "Paper 2", "abstract": "Abstract 2"},
    ]

    cards = await generate_evidence_cards_batch(papers, concurrency=2, timeout_s=0)

    assert len(cards) == 2
    assert all(card["source_api"] == "fallback_missing_card" for card in cards)
