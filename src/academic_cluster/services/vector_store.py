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
        *,
        model_name: str,
    ) -> None:
        """
        添加嵌入向量

        Args:
            paper_ids: 论文 ID 列表
            embeddings: 嵌入向量列表
            model_name: 模型名称
        """
        if len(paper_ids) != len(embeddings):
            raise ValueError(
                "paper_ids and embeddings must contain the same number of items"
            )

        async with self.db.session() as session:
            for paper_id, embedding in zip(paper_ids, embeddings, strict=True):
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

    async def get_knn_graph(
        self,
        paper_ids: list[str],
        k: int = 10,
        threshold: float = 0.5,
        *,
        model_name: str,
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
        if not paper_ids or k <= 0:
            return []
        async with self.db.session() as session:
            result = await session.execute(
                text("""
                    WITH project_embeddings AS MATERIALIZED (
                        SELECT DISTINCT ON (paper_id) paper_id, vector
                        FROM embeddings
                        WHERE paper_id = ANY(CAST(:paper_ids AS uuid[]))
                          AND model_name = :model_name
                          AND vector IS NOT NULL
                        ORDER BY paper_id, created_at DESC
                    )
                    SELECT source.paper_id, neighbor.paper_id, neighbor.similarity
                    FROM project_embeddings AS source
                    CROSS JOIN LATERAL (
                        SELECT candidate.paper_id,
                               1 - (source.vector <=> candidate.vector) AS similarity
                        FROM project_embeddings AS candidate
                        WHERE candidate.paper_id <> source.paper_id
                          AND 1 - (source.vector <=> candidate.vector) >= :threshold
                        ORDER BY source.vector <=> candidate.vector
                        LIMIT :neighbor_count
                    ) AS neighbor
                """),
                {
                    "paper_ids": list(dict.fromkeys(paper_ids)),
                    "neighbor_count": k,
                    "threshold": threshold,
                    "model_name": model_name,
                },
            )
            rows = result.fetchall()

        edges = [
            {
                "source": str(row[0]),
                "target": str(row[1]),
                "weight": float(row[2]),
            }
            for row in rows
        ]

        logger.info("Project-scoped KNN graph built", edges=len(edges))
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
