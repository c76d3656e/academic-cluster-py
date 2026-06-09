"""
社区检测节点 - 构建混合图并进行 Leiden 社区检测
"""

import structlog

from ...services.database import get_database
from ...services.vector_store import get_vector_store
from ...tools.clustering import build_hybrid_graph, leiden_clustering
from ..state import PipelineState

logger = structlog.get_logger()


async def community_detection_node(state: PipelineState) -> dict:
    """
    社区检测

    1. 构建混合图（5种边信号融合）：
       - Vector KNN (weight: 0.45)
       - KG Relation (weight: 0.25)
       - Shared Entity (weight: 0.15)
       - Evidence (weight: 0.10)
       - Quality Prior (weight: 0.05)

    2. Leiden 社区检测：
       - Modularity 质量函数
       - resolution=1.0
       - seed=42
       - max 100 iterations
    """
    logger.info("Starting community detection")

    config = state.config or {}
    resolution = config.get("clustering_resolution", 1.0)
    weights = config.get("hybrid_graph_weights", {
        "knn": 0.45,
        "kg_relation": 0.25,
        "shared_entity": 0.15,
        "evidence": 0.10,
        "quality": 0.05,
    })

    db = get_database()
    vector_store = get_vector_store()

    try:
        # 获取 KNN 边
        knn_edges = await vector_store.get_knn_graph(k=10, threshold=0.3)

        # 获取知识图谱数据
        kg_entities = []
        kg_relations = []
        for entity_id in state.kg_entity_ids:
            # TODO: 从数据库获取实体详情
            pass

        # 获取证据卡片
        evidence_cards = []
        for card_id in state.evidence_card_ids:
            # TODO: 从数据库获取证据卡片详情
            pass

        # 构建混合图
        hybrid_graph = build_hybrid_graph(
            knn_edges=knn_edges,
            kg_relations=kg_relations,
            kg_entities=kg_entities,
            evidence_cards=evidence_cards,
            core_paper_ids=state.core_paper_ids,
            weights=weights,
        )

        # Leiden 社区检测
        clusters = leiden_clustering(
            graph=hybrid_graph,
            resolution=resolution,
            seed=42,
        )

        # 保存聚类结果
        cluster_ids = []
        for cluster in clusters:
            cluster_id = await db.save_cluster(cluster)
            cluster_ids.append(cluster_id)

        logger.info(
            "Community detection completed",
            clusters=len(cluster_ids),
            total_nodes=hybrid_graph.number_of_nodes(),
            total_edges=hybrid_graph.number_of_edges(),
        )

        return {
            "cluster_ids": cluster_ids,
            "hybrid_graph_id": f"hybrid_{state.project_id}",
            "status": "clustered",
        }

    except Exception as e:
        logger.error("Community detection failed", error=str(e))
        return {
            "cluster_ids": [],
            "hybrid_graph_id": None,
            "status": "clustered",
            "errors": [f"Community detection failed: {str(e)}"],
        }
