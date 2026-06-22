"""
向量存储服务

使用 PostgreSQL pgvector 进行向量存储和检索。
"""

from typing import Any

import structlog
from sqlalchemy import text

from .database import get_database

logger = structlog.get_logger()


class VectorStoreService:
    """基于 pgvector 的向量存储服务"""

    def __init__(self) -> None:
        self.db = get_database()
        logger.info("Vector store service initialized (pgvector)")

    async def add_embeddings(
        self,
        paper_ids: list[str],
        embeddings: list[list[float]],
        model_name: str = "bge-m3",
    ) -> None:
        """
        添加嵌入向量

        Args:
            paper_ids: 论文 ID 列表
            embeddings: 嵌入向量列表
            model_name: 模型名称
        """
        async with self.db.session() as session:
            for paper_id, embedding in zip(paper_ids, embeddings, strict=False):
                # 使用 UPSERT 语义
                await session.execute(
                    text("""
                        INSERT INTO embeddings (paper_id, model_name, vector, dimensions)
                        VALUES (:paper_id, :model_name, :vector, :dimensions)
                        ON CONFLICT (paper_id, model_name)
                        DO UPDATE SET vector = :vector, dimensions = :dimensions
                    """),
                    {
                        "paper_id": paper_id,
                        "model_name": model_name,
                        "vector": str(embedding),
                        "dimensions": len(embedding),
                    },
                )

        logger.info("Added embeddings", count=len(paper_ids))

    async def search_similar(
        self,
        query_embedding: list[float],
        limit: int = 10,
        threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        """
        搜索相似向量

        Args:
            query_embedding: 查询向量
            limit: 返回结果数
            threshold: 相似度阈值

        Returns:
            相似论文列表
        """
        async with self.db.session() as session:
            result = await session.execute(
                text("""
                    SELECT paper_id, similarity
                    FROM search_similar_papers(:query_embedding, :limit, :threshold)
                """),
                {
                    "query_embedding": str(query_embedding),
                    "limit": limit,
                    "threshold": threshold,
                },
            )

            rows = result.fetchall()

        return [{"paper_id": str(row[0]), "similarity": row[1]} for row in rows]

    async def get_knn_graph(
        self,
        paper_ids: list[str],
        k: int = 10,
        threshold: float = 0.5,
    ) -> list[dict[str, Any]]:
        """
        获取 KNN 图

        Args:
            paper_ids: 论文 ID 列表
            k: 每个节点的近邻数
            threshold: 相似度阈值

        Returns:
            边列表 [{source, target, weight}]
        """
        edges = []

        async with self.db.session() as session:
            for paper_id in paper_ids:
                # 获取该论文的嵌入向量
                result = await session.execute(
                    text("""
                        SELECT vector FROM embeddings
                        WHERE paper_id = :paper_id
                        LIMIT 1
                    """),
                    {"paper_id": paper_id},
                )
                row = result.fetchone()

                if not row or not row[0]:
                    continue

                vector = row[0]

                # 搜索相似论文
                similar = await self.search_similar(
                    query_embedding=vector,
                    limit=k + 1,
                    threshold=threshold,
                )

                for item in similar:
                    if item["paper_id"] != paper_id:
                        edges.append(
                            {
                                "source": paper_id,
                                "target": item["paper_id"],
                                "weight": item["similarity"],
                            }
                        )

        logger.info("KNN graph built", edges=len(edges))
        return edges

    async def close(self) -> None:
        """关闭连接"""
        logger.info("Vector store connection closed")


# 全局向量存储实例
_vector_store: VectorStoreService | None = None


def get_vector_store() -> VectorStoreService:
    """获取向量存储服务单例"""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStoreService()
    return _vector_store


async def close_vector_store() -> None:
    """关闭向量存储连接"""
    global _vector_store
    if _vector_store is not None:
        await _vector_store.close()
        _vector_store = None
