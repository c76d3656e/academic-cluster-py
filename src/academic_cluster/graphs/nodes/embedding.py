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
from ...services.observability import get_current_tracker
from ..state import PipelineState
from .progress import send_progress

logger = structlog.get_logger()


async def generate_embedding(text: str, timeout: float = 30.0) -> list[float]:
    """
    生成文本嵌入向量

    通过 Provider Pool 自动选择可用的 Embedding 端点。
    超时保护：单次调用超过 timeout 秒则抛出 TimeoutError。
    """
    import time as _time

    from ...services.provider_pool import get_embedding_pool
    from ...services.observability import get_current_tracker, get_current_node

    pool = get_embedding_pool()
    start_time = _time.monotonic()
    provider_alias = pool.get_model_name()

    response = await asyncio.wait_for(
        pool.router.aembedding(
            model=provider_alias,
            input=[text],
        ),
        timeout=timeout,
    )

    elapsed_ms = int((_time.monotonic() - start_time) * 1000)

    # 记录 embedding 调用到 tracker 和 DB
    from ...services.observability import get_resolved_run_id
    tracker = get_current_tracker()
    run_id = get_resolved_run_id()
    if run_id:
        try:
            from ...services.database import get_database
            from ...api.admin.providers import get_provider_pricing

            db = get_database()
            node_name = get_current_node() or "embedding"

            # embedding 的 token 用量：input_tokens = len(text) 近似
            # 大多数 embedding API 不返回 token 用量，用字符数近似
            prompt_tokens = len(text) // 2  # 粗略估计
            completion_tokens = 0  # embedding 没有 output tokens

            # 计算 cost
            input_price, output_price = await get_provider_pricing(db, provider_alias, "bge-m3")
            cost = 0.0
            if input_price:
                cost = (prompt_tokens * input_price) / 1_000_000

            # 记录到 tracker
            if tracker:
                await tracker.token_tracker.record(
                    node_name=node_name,
                    provider_name=provider_alias,
                    model_name="bge-m3",
                    call_type="embedding",
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                    cost=cost,
                    latency_ms=elapsed_ms,
                )

            # 持久化到 DB
            from ...services.observability import get_current_project
            project_id_for_call = getattr(tracker, "project_id", None) or get_current_project()
            exec_id = await db.create_node_execution(run_id, node_name, "embedding")
            call_id = await db.create_llm_call(
                pipeline_run_id=run_id,
                node_execution_id=exec_id,
                project_id=project_id_for_call,
                node_name=node_name,
                call_type="embedding",
                provider_name=provider_alias,
                model_name="bge-m3",
                requested_model="bge-m3",
                upstream_model="bge-m3",
                latency_ms=elapsed_ms,
                request_metadata={
                    "node_name": node_name,
                    "provider_alias": provider_alias,
                },
            )
            await db.finish_llm_call(
                call_id=call_id,
                status="success",
                prompt_tokens=prompt_tokens,
                completion_tokens=0,
                cost=cost,
                latency_ms=elapsed_ms,
            )
        except Exception:
            pass  # 追踪失败不影响主流程

    return response.data[0]["embedding"]


async def embedding_node(state: PipelineState) -> dict:
    """
    生成论文嵌入向量

    使用 Embedding API 生成论文的向量表示：
    - 批量处理论文（标题 + 摘要）
    - 存储到向量数据库
    - 返回嵌入 ID 列表
    """
    tracker = get_current_tracker()
    if tracker:
        await tracker.begin_node("embedding", "compute", index=1)

    try:
        config = state.config or {}
        max_papers = config.get("max_embedding_papers", 1000)
        paper_ids = state.paper_ids[:max_papers]

        logger.info("Starting embedding generation", paper_count=len(paper_ids))

        await send_progress(
            state.project_id, "embedding",
            f"正在向量化 {len(paper_ids)} 篇论文...",
        )

        db = get_database()
        cache = get_cache()
        vector_store = get_vector_store()

        # 获取论文详情
        papers = await db.get_papers_by_ids(paper_ids)

        embedding_ids = []
        embeddings_data = []
        embed_sem = asyncio.Semaphore(20)  # 并发上限，充分利用多 provider

        async def _process_one(paper: dict) -> dict | None:
            paper_id = paper.get("id")
            title = paper.get("title", "")
            abstract = paper.get("abstract", "")
            text = f"{title} {abstract}".strip()

            if not text:
                logger.warning("Skipping paper with no text", paper_id=paper_id)
                return None

            async with embed_sem:
                cached_embedding = await cache.get_embedding(paper_id, "bge-m3")
                if cached_embedding:
                    embedding = cached_embedding
                else:
                    try:
                        embedding = await generate_embedding(text)
                        await cache.set_embedding(paper_id, "bge-m3", embedding)
                    except asyncio.TimeoutError:
                        logger.error(
                            "Embedding generation timed out",
                            paper_id=paper_id, title_length=len(title),
                            abstract_length=len(abstract), timeout_seconds=30,
                        )
                        return None
                    except Exception as e:
                        logger.error(
                            "Failed to generate embedding",
                            paper_id=paper_id, title=title[:100],
                            error=str(e), error_type=type(e).__name__,
                        )
                        return None

            return {
                "id": f"emb_{paper_id}",
                "paper_id": paper_id,
                "embedding": embedding,
                "text": text[:500],
            }

        results = await asyncio.gather(*[_process_one(p) for p in papers])
        for r in results:
            if r is not None:
                embedding_ids.append(r["id"])
                embeddings_data.append(r)

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
            "paper_ids": paper_ids,
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
