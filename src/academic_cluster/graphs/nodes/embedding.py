"""
嵌入节点 - 生成论文嵌入向量

使用 Provider Pool（LiteLLM Router）自动负载均衡多个 Embedding 端点。
"""

import asyncio
import traceback

import structlog

from ...services.database import get_database
from ...services.cache import get_cache
from ...services.vector_store import get_vector_store
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()


async def generate_embedding(text: str, timeout: float = 30.0) -> list[float]:
    """
    生成文本嵌入向量

    通过 Provider Pool 自动选择可用的 Embedding 端点。
    超时保护：单次调用超过 timeout 秒则抛出 TimeoutError。
    """
    from ...services.provider_pool import get_embedding_pool

    pool = get_embedding_pool()
    response = await asyncio.wait_for(
        pool.router.aembedding(
            model=pool.get_model_name(),
            input=[text],
        ),
        timeout=timeout,
    )
    return response.data[0]["embedding"]


async def embedding_node(state: PipelineState) -> dict:
    """
    生成论文嵌入向量

    使用 Embedding API 生成论文的向量表示：
    - 批量处理论文（标题 + 摘要）
    - 存储到向量数据库
    - 返回嵌入 ID 列表
    """
    tracker = state.tracker if hasattr(state, 'tracker') else None
    if tracker:
        await tracker.begin_node("embedding", "compute", index=1)

    try:
        logger.info("Starting embedding generation", paper_count=len(state.paper_ids))

        await send_progress(
            state.project_id, "embedding",
            f"正在向量化 {len(state.paper_ids)} 篇论文...",
        )

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
                    # 生成嵌入（通过 Provider Pool 自动负载均衡）
                    embedding = await generate_embedding(text)
                    # 缓存嵌入
                    await cache.set_embedding(paper_id, "bge-m3", embedding)
                except asyncio.TimeoutError:
                    logger.error(
                        "Embedding generation timed out",
                        paper_id=paper_id,
                        title_length=len(title),
                        abstract_length=len(abstract),
                        timeout_seconds=30,
                    )
                    continue
                except Exception as e:
                    logger.error(
                        "Failed to generate embedding",
                        paper_id=paper_id,
                        title=title[:100],
                        error=str(e),
                        error_type=type(e).__name__,
                    )
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
                    paper_ids=[e["paper_id"] for e in embeddings_data],
                    embeddings=[e["embedding"] for e in embeddings_data],
                )
            except Exception as e:
                logger.error(
                    "Failed to store embeddings in vector DB",
                    embedding_count=len(embeddings_data),
                    error=str(e),
                    error_type=type(e).__name__,
                )

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

        await send_progress(
            state.project_id, "embedding",
            f"向量化完成，共 {len(embedding_ids)} 篇",
        )

        result = {
            "embedding_ids": embedding_ids,
            "status": "embedded",
        }

        if tracker:
            await tracker.end_node("embedding", "succeeded", output_summary={
                "embedding_count": len(embedding_ids),
            })
        return result

    except Exception as e:
        logger.error(
            "Embedding node failed",
            project_id=state.project_id,
            paper_count=len(state.paper_ids),
            error=str(e),
            error_type=type(e).__name__,
            traceback=traceback.format_exc(),
        )
        if tracker:
            await tracker.end_node("embedding", "failed",
                                   error_message=str(e),
                                   error_traceback=traceback.format_exc())
        raise
