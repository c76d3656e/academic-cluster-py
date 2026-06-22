import asyncio
from types import SimpleNamespace

from academic_cluster.graphs.nodes.gap_analysis import gap_analysis_node


class _FakeGapDb:
    async def get_clusters_by_ids(self, ids):
        return [{"id": "cluster-1", "paper_ids": ["p1", "p2", "p3", "p4"]}]

    async def get_evidence_cards_by_ids(self, ids):
        return []

    async def get_kg_entities_by_ids(self, ids):
        return []

    async def get_papers_by_ids(self, ids):
        return [
            {"id": pid, "title": f"Paper {pid}", "abstract": "Abstract"} for pid in ids
        ]


async def test_gap_analysis_timeout_keeps_pipeline_moving(monkeypatch):
    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.gap_analysis.get_database",
        lambda: _FakeGapDb(),
    )

    state = SimpleNamespace(
        project_id="project-1",
        query="topic",
        cluster_ids=["cluster-1"],
        evidence_card_ids=[],
        kg_entity_ids=[],
        reranked_paper_ids=["p1", "p2", "p3", "p4"],
        paper_ids=["p1", "p2", "p3", "p4"],
        refinement_attempt=0,
        max_refinement_attempts=5,
        config={"gap_analysis_timeout_s": 0},
    )

    async def timeout_judge(topic, gap_reports, timeout_s=45):
        await asyncio.sleep(0)
        return gap_reports, False

    monkeypatch.setattr(
        "academic_cluster.graphs.nodes.gap_analysis._refine_gaps_with_llm",
        timeout_judge,
    )

    result = await gap_analysis_node(state)

    assert result["status"] == "gaps_analyzed"
    assert result["gap_analysis_ids"] == ["cluster-1"]
    assert result["needs_targeted_refinement"] is False
