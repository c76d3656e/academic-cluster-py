"""
嵌入 API 集成测试

使用真实的 Embedding API 进行测试。
"""

import pytest

from academic_cluster.config import get_settings
from academic_cluster.graphs.nodes.embedding import generate_embedding


@pytest.mark.integration
@pytest.mark.asyncio
async def test_generate_embedding():
    """测试生成嵌入向量"""
    text = "Machine learning is a subset of artificial intelligence."

    embedding = await generate_embedding(text)

    # 验证返回结果
    assert isinstance(embedding, list)
    assert len(embedding) > 0

    # 验证向量维度（BAAI/bge-m3 应该是 1024 维）
    settings = get_settings()
    expected_dims = settings.embedding.dimensions
    assert len(embedding) == expected_dims

    # 验证向量值范围
    assert all(isinstance(v, (int, float)) for v in embedding)

    print(f"Embedding generated: {len(embedding)} dimensions")
    print(f"First 5 values: {embedding[:5]}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_embedding_consistency():
    """测试嵌入的一致性"""
    text = "Deep learning neural networks"

    # 生成两次嵌入
    embedding1 = await generate_embedding(text)
    embedding2 = await generate_embedding(text)

    # 验证维度相同
    assert len(embedding1) == len(embedding2)

    # 验证值相似（由于 API 可能有微小差异，使用近似比较）
    for v1, v2 in zip(embedding1[:10], embedding2[:10], strict=False):
        assert abs(v1 - v2) < 0.01

    print("Embedding consistency test passed")
