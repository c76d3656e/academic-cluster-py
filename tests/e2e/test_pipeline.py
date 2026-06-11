"""
Pipeline 端到端测试

测试完整的学术论文聚类和综述生成流程。
使用真实 API 调用，每个数据源限制 2 篇论文。
"""

import asyncio
import uuid

import pytest

from academic_cluster.graphs.state import PipelineState
from academic_cluster.graphs.graph import compile_graph


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_full_pipeline():
    """
    测试完整的 Pipeline 流程

    使用限制数量的论文进行快速验证。
    """
    project_id = str(uuid.uuid4())
    query = "transformer attention mechanism"

    # 创建初始状态
    initial_state = PipelineState(
        project_id=project_id,
        query=query,
        config={
            "limit_per_source": 10,  # 每个数据源 10 篇
            "sources": ["arxiv", "semantic_scholar"],
            "max_embedding_papers": 20,
            "core_reference_count": 10,
            "auxiliary_reference_count": 5,
        },
    )

    # 编译图
    graph = compile_graph(debug=True, interrupt_before=[])

    # 执行 Pipeline
    try:
        result = await graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": project_id}},
        )

        # 验证结果
        assert result is not None
        assert result.get("paper_ids") is not None
        assert len(result.get("paper_ids", [])) > 0

        # 验证综述内容
        final_review = result.get("final_review", "")
        assert final_review, "Final review should not be empty"
        assert len(final_review) > 1000, f"Review too short: {len(final_review)} chars"

        # 验证引用格式
        import re
        citations = re.findall(r'\[\d+(?:,\d+)*\]', final_review)
        assert len(citations) >= 5, f"Too few citations: {len(citations)}"

        # 验证 BibTeX
        bibtex = result.get("bibtex", "")
        assert bibtex, "BibTeX should not be empty"
        assert "@article{" in bibtex, "BibTeX should contain @article entries"
        assert "None" not in bibtex, "BibTeX should not contain 'None' values"

        # 验证大纲有章节标题
        outline_data = result.get("outline_data", {})
        sections = outline_data.get("sections", [])
        assert len(sections) >= 2, f"Outline should have >= 2 sections, got {len(sections)}"

        print(f"\n=== Pipeline 结果 ===")
        print(f"项目 ID: {project_id}")
        print(f"论文数量: {len(result.get('paper_ids', []))}")
        print(f"综述长度: {len(final_review)} 字符")
        print(f"引用数量: {len(citations)}")
        print(f"章节数量: {len(sections)}")
        print(f"状态: {result.get('status')}")

        return result

    except Exception as e:
        pytest.fail(f"Pipeline failed: {str(e)}")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_search_only():
    """
    仅测试搜索节点

    验证学术搜索 API 调用是否正常工作。
    """
    from academic_cluster.graphs.nodes.search import search_node

    state = PipelineState(
        project_id=str(uuid.uuid4()),
        query="machine learning",
        config={
            "limit_per_source": 2,
            "sources": ["arxiv"],
        },
    )

    result = await search_node(state)

    assert "paper_ids" in result
    assert "status" in result
    assert result["status"] == "searched"

    print(f"\n=== 搜索结果 ===")
    print(f"论文数量: {len(result.get('paper_ids', []))}")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_embedding_generation():
    """
    测试嵌入生成

    验证 Embedding API 调用是否正常工作。
    """
    from academic_cluster.graphs.nodes.embedding import generate_embedding

    text = "Machine learning is a subset of artificial intelligence."

    embedding = await generate_embedding(text)

    assert isinstance(embedding, list)
    assert len(embedding) == 1024

    print(f"\n=== 嵌入生成结果 ===")
    print(f"向量维度: {len(embedding)}")
    print(f"前5个值: {embedding[:5]}")


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_rerank():
    """
    测试重排序

    验证 Rerank API 调用是否正常工作。
    """
    from academic_cluster.graphs.nodes.rerank import rerank_papers

    query = "deep learning"
    papers = [
        {
            "id": "paper_1",
            "title": "Deep Learning for Image Classification",
            "abstract": "We propose a deep learning approach.",
        },
        {
            "id": "paper_2",
            "title": "Natural Language Processing",
            "abstract": "NLP techniques for text analysis.",
        },
    ]

    reranked = await rerank_papers(query, papers)

    assert len(reranked) == 2
    assert all("rerank_score" in p for p in reranked)

    print(f"\n=== 重排序结果 ===")
    for p in reranked:
        print(f"  {p.get('title', '')[:50]}: {p['rerank_score']:.4f}")
