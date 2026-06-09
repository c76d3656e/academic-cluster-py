"""
嵌入节点 - 生成论文嵌入向量
"""

import asyncio

import httpx
import structlog

from ...config import get_settings
from ...services.database import get_database
from ...services.cache import get_cache
from ...services.vector_store import get_vector_store
from ..state import PipelineState

logger = structlog.get_logger()


async def generate_embedding(text: str) -> list[float]:
    """
    生成文本嵌入向量

    调用 Embedding API（如 SiliconFlow 的 BAAI/bge-m3）
    """
    settings = get_settings()

    url = f"{settings.embedding.api_url}/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.embedding.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.embedding.model,
        "input": text,
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        return data["data"][0]["embedding"]


async def embedding_node(state: PipelineState) -> dict:
    """
    生成论文嵌入向量

    使用 Embedding API 生成论文的向量表示：
    - 批量处理论文（标题 + 摘要）
    - 存储到向量数据库
    - 返回嵌入 ID 列表
    """
    logger.info("Starting embedding generation", paper_count=len(state.paper_ids))

    db = get_database()
    cache = get_cache()
    vector_store = get_vector_store()

    # 获取论文详情
    papers = await db.get_papers_by_ids(state.paper_ids)

    embedding_ids = []
    embeddings_data = []

    for paper in papers:
        paper_id = paper.get("id")
        title = paper.get("title", "")
        abstract = paper.get("abstract", "")
        text = f"{title} {abstract}".strip()

        if not text:
            logger.warning("Skipping paper with no text", paper_id=paper_id)
            continue

        # 检查缓存
        cached_embedding = await cache.get_embedding(paper_id, "bge-m3")
        if cached_embedding:
            embedding = cached_embedding
        else:
            try:
                # 生成嵌入
                embedding = await generate_embedding(text)
                # 缓存嵌入
                await cache.set_embedding(paper_id, "bge-m3", embedding)
            except Exception as e:
                logger.error("Failed to generate embedding", paper_id=paper_id, error=str(e))
                continue

        embedding_id = f"emb_{paper_id}"
        embedding_ids.append(embedding_id)
        embeddings_data.append({
            "id": embedding_id,
            "paper_id": paper_id,
            "embedding": embedding,
            "text": text[:500],  # 存储部分文本用于检索
        })

    # 批量存储到向量数据库
    if embeddings_data:
        try:
            await vector_store.add_embeddings(
                ids=[e["id"] for e in embeddings_data],
                embeddings=[e["embedding"] for e in embeddings_data],
                metadatas=[{"paper_id": e["paper_id"]} for e in embeddings_data],
                documents=[e["text"] for e in embeddings_data],
            )
        except Exception as e:
            logger.error("Failed to store embeddings in vector DB", error=str(e))

    # 保存嵌入记录到数据库
    for emb_data in embeddings_data:
        await db.save_embedding(
            paper_id=emb_data["paper_id"],
            embedding=emb_data["embedding"],
            model_name="bge-m3",
        )

    logger.info(
        "Embedding generation completed",
        papers_processed=len(papers),
        embeddings_created=len(embedding_ids),
    )

    return {
        "embedding_ids": embedding_ids,
        "status": "embedded",
    }
