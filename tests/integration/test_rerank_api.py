"""
Rerank API 集成测试

使用真实的 Rerank API 进行测试。
"""

import pytest

from academic_cluster.graphs.nodes.rerank import rerank_papers


@pytest.mark.integration
@pytest.mark.asyncio
async def test_rerank_papers():
    """测试重排序论文"""
    query = "machine learning classification"

    papers = [
        {
            "id": "paper_1",
            "title": "Deep Learning for Image Classification",
            "abstract": "We propose a deep learning approach for image classification tasks.",
        },
        {
            "id": "paper_2",
            "title": "A Survey of Machine Learning Algorithms",
            "abstract": "This paper surveys various machine learning algorithms including classification methods.",
        },
        {
            "id": "paper_3",
            "title": "Natural Language Processing with Transformers",
            "abstract": "We present transformer models for NLP tasks.",
        },
    ]

    reranked = await rerank_papers(query, papers)

    # 验证返回结果
    assert isinstance(reranked, list)
    assert len(reranked) == len(papers)

    # 验证每个论文都有 rerank_score
    for paper in reranked:
        assert "rerank_score" in paper
        assert isinstance(paper["rerank_score"], (int, float))

    # 验证排序（分数应该从高到低）
    scores = [p["rerank_score"] for p in reranked]
    assert scores == sorted(scores, reverse=True)

    print("Rerank test passed")
    for paper in reranked:
        print(f"  {paper.get('title', '')[:50]}: {paper['rerank_score']:.4f}")
