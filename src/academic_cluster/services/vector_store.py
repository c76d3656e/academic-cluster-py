"""
向量存储服务

提供向量数据库访问（ChromaDB/pgvector）。
"""

from typing import Optional

import structlog

from ..config import get_settings

logger = structlog.get_logger()


class VectorStoreService:
    """向量存储服务"""

    def __init__(self, provider: Optional[str] = None):
        settings = get_settings()

        if provider is None:
            provider = settings.vector_db.provider

        self.provider = provider
        self._client = None
        self._collection = None

        logger.info("Vector store service initialized", provider=provider)

    async def _get_client(self):
        """获取向量数据库客户端"""
        if self._client is None:
            if self.provider == "chromadb":
                import chromadb
                settings = get_settings()
                self._client = chromadb.HttpClient(
                    host=settings.vector_db.host,
                    port=settings.vector_db.port,
                )
            else:
                raise ValueError(f"Unsupported vector store provider: {self.provider}")

        return self._client

    async def _get_collection(self, collection_name: str = "papers"):
        """获取或创建集合"""
        client = await self._get_client()

        if self._collection is None:
            self._collection = client.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"},
            )

        return self._collection

    async def add_embeddings(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        metadatas: Optional[list[dict]] = None,
        documents: Optional[list[str]] = None,
    ):
        """
        添加嵌入向量

        Args:
            ids: 向量 ID 列表
            embeddings: 嵌入向量列表
            metadatas: 元数据列表
            documents: 文档文本列表
        """
        collection = await self._get_collection()

        collection.add(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas,
            documents=documents,
        )

        logger.info("Added embeddings", count=len(ids))

    async def query(
        self,
        query_embedding: list[float],
        n_results: int = 10,
        where: Optional[dict] = None,
    ) -> dict:
        """
        查询相似向量

        Args:
            query_embedding: 查询向量
            n_results: 返回结果数
            where: 过滤条件

        Returns:
            查询结果
        """
        collection = await self._get_collection()

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where,
        )

        return results

    async def get_knn_graph(
        self,
        k: int = 10,
        threshold: float = 0.5,
    ) -> list[dict]:
        """
        获取 KNN 图

        Args:
            k: 每个节点的近邻数
            threshold: 相似度阈值

        Returns:
            边列表 [{source, target, weight}]
        """
        collection = await self._get_collection()

        # 获取所有向量
        all_data = collection.get(include=["embeddings"])
        ids = all_data["ids"]
        embeddings = all_data["embeddings"]

        edges = []
        for i, (id_a, emb_a) in enumerate(zip(ids, embeddings)):
            # 查询最近邻
            results = collection.query(
                query_embeddings=[emb_a],
                n_results=k + 1,  # +1 因为包含自身
            )

            for j, (id_b, distance) in enumerate(zip(
                results["ids"][0],
                results["distances"][0],
            )):
                if id_a != id_b:
                    # ChromaDB 返回距离，需要转换为相似度
                    similarity = 1 - distance
                    if similarity >= threshold:
                        edges.append({
                            "source": id_a,
                            "target": id_b,
                            "weight": similarity,
                        })

        logger.info("KNN graph built", edges=len(edges))

        return edges

    async def delete_collection(self, collection_name: str = "papers"):
        """删除集合"""
        client = await self._get_client()
        client.delete_collection(collection_name)
        logger.info("Collection deleted", name=collection_name)

    async def close(self):
        """关闭连接"""
        self._client = None
        self._collection = None
        logger.info("Vector store connection closed")


# 全局向量存储实例
_vector_store: Optional[VectorStoreService] = None


def get_vector_store() -> VectorStoreService:
    """获取向量存储服务单例"""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStoreService()
    return _vector_store


async def close_vector_store():
    """关闭向量存储连接"""
    global _vector_store
    if _vector_store is not None:
        await _vector_store.close()
        _vector_store = None
