"""
测试配置
"""

import asyncio

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def event_loop():
    """创建事件循环"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def mock_database():
    """模拟数据库服务"""
    # TODO: 实现模拟数据库
    pass


@pytest_asyncio.fixture
async def mock_cache():
    """模拟缓存服务"""
    # TODO: 实现模拟缓存
    pass


@pytest_asyncio.fixture
async def mock_vector_store():
    """模拟向量存储"""
    # TODO: 实现模拟向量存储
    pass


@pytest.fixture
def sample_paper():
    """示例论文数据"""
    return {
        "id": "paper_001",
        "external_id": "S2:12345",
        "source": "semantic_scholar",
        "title": "Sample Paper Title",
        "abstract": "This is a sample abstract for testing purposes.",
        "authors": [{"name": "Author One"}, {"name": "Author Two"}],
        "year": 2024,
        "citation_count": 10,
        "fields_of_study": ["Computer Science"],
    }


@pytest.fixture
def sample_papers():
    """示例论文列表"""
    return [
        {
            "id": f"paper_{i:03d}",
            "external_id": f"S2:{i}",
            "source": "semantic_scholar",
            "title": f"Paper Title {i}",
            "abstract": f"Abstract for paper {i}",
            "authors": [{"name": f"Author {i}"}],
            "year": 2024 - i % 5,
            "citation_count": i * 10,
            "fields_of_study": ["Computer Science"],
        }
        for i in range(10)
    ]


@pytest.fixture
def sample_cluster():
    """示例聚类数据"""
    return {
        "id": "cluster_0",
        "name": "Machine Learning",
        "paper_ids": ["paper_001", "paper_002", "paper_003"],
        "size": 3,
        "main_topics": ["deep learning", "neural networks"],
    }
