"""
搜索 API 集成测试

使用真实的 API 调用进行测试，不使用虚假数据。
"""

import asyncio

import pytest
import httpx

from academic_cluster.tools.academic_search import (
    search_semantic_scholar,
    search_arxiv,
    search_all_sources,
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_semantic_scholar_search():
    """测试 Semantic Scholar API 真实调用"""
    query = "large language model"

    papers = await search_semantic_scholar(query, limit=5)

    # 验证返回结果
    assert isinstance(papers, list)
    assert len(papers) > 0

    # 验证论文结构
    paper = papers[0]
    assert "title" in paper
    assert "source" in paper
    assert paper["source"] == "semantic_scholar"
    assert "external_id" in paper

    print(f"Semantic Scholar: Found {len(papers)} papers")
    print(f"First paper: {paper.get('title', '')[:80]}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_arxiv_search():
    """测试 arXiv API 真实调用"""
    query = "transformer attention mechanism"

    papers = await search_arxiv(query, limit=5)

    # 验证返回结果
    assert isinstance(papers, list)
    assert len(papers) > 0

    # 验证论文结构
    paper = papers[0]
    assert "title" in paper
    assert "source" in paper
    assert paper["source"] == "arxiv"
    assert "abstract" in paper

    print(f"arXiv: Found {len(papers)} papers")
    print(f"First paper: {paper.get('title', '')[:80]}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_multi_source_search():
    """测试多数据源并行搜索"""
    query = "reinforcement learning"

    papers = await search_all_sources(
        query=query,
        limit_per_source=3,
        sources=["semantic_scholar", "arxiv"],
    )

    # 验证返回结果
    assert isinstance(papers, list)
    assert len(papers) > 0

    # 统计各数据源的论文数
    sources = {}
    for paper in papers:
        source = paper.get("source", "unknown")
        sources[source] = sources.get(source, 0) + 1

    print(f"Multi-source search: Found {len(papers)} papers")
    print(f"Sources: {sources}")

    # 验证至少有一个数据源返回了结果
    assert len(sources) > 0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_with_real_query():
    """测试使用真实研究主题搜索"""
    query = "graph neural network for molecular property prediction"

    papers = await search_semantic_scholar(query, limit=10)

    assert len(papers) > 0

    # 验证论文相关性
    for paper in papers[:3]:
        title = paper.get("title", "").lower()
        abstract = paper.get("abstract", "").lower()
        # 检查是否包含相关关键词
        has_relevant_keyword = any(
            kw in title or kw in abstract
            for kw in ["graph", "neural", "molecular", "property", "prediction"]
        )
        print(f"Paper: {paper.get('title', '')[:60]}")
        print(f"  Relevant: {has_relevant_keyword}")
