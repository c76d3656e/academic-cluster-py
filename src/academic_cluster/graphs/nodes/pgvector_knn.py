"""
pgvector KNN 节点 - 存储嵌入并计算 KNN 图
"""

from typing import Any

import structlog

from ...services.database import get_database
from ...services.vector_store import get_vector_store
from ..state import PipelineState

logger = structlog.get_logger()


async def pgvector_knn_node(state: PipelineState) -> dict[str, Any]:
    """
    计算 KNN 图

    使用向量数据库计算 K 近邻图：
    - 获取所有嵌入向量
    - 计算余弦相似度
    - 构建 KNN 图（每个论文的 Top-K 相似论文）
    """
    logger.info(
        "Starting KNN graph computation", embedding_count=len(state.embedding_ids)
    )

    config = state.config or {}
    k = config.get("knn_k", 10)
    threshold = config.get("knn_threshold", 0.5)

    vector_store = get_vector_store()

    try:
        # 获取 KNN 图
        knn_edges = await vector_store.get_knn_graph(
            paper_ids=state.paper_ids, k=k, threshold=threshold
        )

        # 保存到数据库
        get_database()
        knn_graph_id = f"knn_{state.project_id}"
        # TODO: 保存 KNN 图到数据库

        logger.info(
            "KNN graph computed",
            edges=len(knn_edges),
        )

        return {
            "knn_graph_id": knn_graph_id,
            "status": "knn_computed",
        }

    except Exception as e:
        logger.error("KNN computation failed", error=str(e))
        return {
            "knn_graph_id": None,
            "status": "knn_computed",
            "errors": [f"KNN computation failed: {e!s}"],
        }
