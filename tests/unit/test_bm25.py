"""
BM25 检索单元测试
"""

import pytest

from academic_cluster.tools.text_processing import BM25, bm25_search


class TestBM25:
    """BM25 算法测试"""

    def test_tokenize(self):
        """测试分词"""
        bm25 = BM25()
        tokens = bm25._tokenize("Hello, World! This is a test.")
        assert tokens == ["hello", "world", "this", "is", "a", "test"]

    def test_fit(self):
        """测试拟合"""
        bm25 = BM25()
        corpus = [
            "machine learning is great",
            "deep learning neural networks",
            "natural language processing",
        ]
        bm25.fit(corpus)

        assert bm25.n_docs == 3
        assert bm25.avg_doc_len > 0
        assert "machine" in bm25.doc_freqs

    def test_score(self):
        """测试评分"""
        bm25 = BM25()
        corpus = [
            "machine learning algorithms",
            "deep learning neural networks",
            "natural language processing",
        ]
        bm25.fit(corpus)

        # 查询与第一篇文档应该有较高分数
        score = bm25.score("machine learning", 0)
        assert score > 0

    def test_search(self):
        """测试搜索"""
        bm25 = BM25()
        corpus = [
            "machine learning algorithms for classification",
            "deep learning neural networks",
            "natural language processing techniques",
            "machine learning applications",
        ]
        bm25.fit(corpus)

        results = bm25.search("machine learning", top_k=2)
        assert len(results) == 2
        # 前两个结果应该是包含 "machine learning" 的文档
        assert results[0][0] in [0, 3]
        assert results[1][0] in [0, 3]


@pytest.mark.asyncio
async def test_bm25_search():
    """测试异步 BM25 搜索接口"""
    documents = [
        {
            "id": "doc1",
            "title": "Machine Learning Basics",
            "abstract": "Introduction to machine learning concepts",
        },
        {
            "id": "doc2",
            "title": "Deep Learning",
            "abstract": "Neural networks and deep learning",
        },
        {
            "id": "doc3",
            "title": "Natural Language Processing",
            "abstract": "Text processing and NLP techniques",
        },
    ]

    results = await bm25_search("machine learning", documents, top_k=2)

    assert len(results) <= 2
    assert results[0]["id"] == "doc1"  # 最相关的应该是第一篇
    assert "bm25_score" in results[0]
