import pytest

from academic_cluster.graphs.nodes.rerank import rerank_papers


class _FailingPool:
    async def execute(self, func, max_retries=None):
        raise RuntimeError("rerank provider failed")


@pytest.mark.asyncio
async def test_rerank_papers_falls_back_when_provider_fails(monkeypatch):
    monkeypatch.setattr(
        "academic_cluster.services.provider_pool.get_rerank_pool",
        lambda: _FailingPool(),
    )

    papers = [
        {
            "id": "paper-1",
            "title": "A",
            "abstract": "Long abstract " * 20,
            "year": 2025,
        },
        {
            "id": "paper-2",
            "title": "B",
            "abstract": "Long abstract " * 20,
            "year": 2020,
        },
    ]

    result = await rerank_papers("agent systems", papers)

    assert {paper["id"] for paper in result} == {"paper-1", "paper-2"}
    assert all(paper["rerank_score"] == 0.0 for paper in result)
    assert all("quality_score" in paper for paper in result)
    assert all("quality_tier" in paper for paper in result)
