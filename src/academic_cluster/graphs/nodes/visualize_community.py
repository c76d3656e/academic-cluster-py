"""
社区可视化节点 - 生成并推送可视化数据给前端
"""

import structlog

from ...services.database import get_database
from ...tools.clustering import generate_community_visualization
from ..state import PipelineState

logger = structlog.get_logger()


async def visualize_community_node(state: PipelineState) -> dict:
    """
    生成社区聚类可视化

    生成可视化数据并推送给前端：
    - 节点：论文（按社区着色）
    - 边：论文间的相似关系
    - 布局：力导向布局
    - 交互：点击节点显示论文详情

    这是大纲规划前的关键步骤，让用户直观了解论文聚类结果。
    """
    logger.info("Generating community visualization")

    db = get_database()

    try:
        # 获取聚类结果
        clusters = await db.get_clusters_by_ids(state.cluster_ids)

        # 获取论文详情（使用全部 reranked 论文进行可视化）
        papers = await db.get_papers_by_ids(state.reranked_paper_ids)

        # 获取混合图（简化版本，只包含核心论文间的边）
        import networkx as nx
        hybrid_graph = nx.Graph()
        for paper in papers:
            hybrid_graph.add_node(paper.get("id"))

        # 生成可视化
        visualization = generate_community_visualization(
            graph=hybrid_graph,
            clusters=clusters,
            papers=papers,
            layout="force",
        )

        logger.info(
            "Community visualization generated",
            nodes=len(visualization.get("nodes", [])),
            edges=len(visualization.get("edges", [])),
            clusters=len(visualization.get("clusters", [])),
        )

        # 保存可视化数据到数据库
        await db.save_visualization(state.project_id, visualization)

        return {
            "community_visualization": visualization,
            "status": "visualized",
        }

    except Exception as e:
        logger.error("Visualization generation failed", error=str(e))
        raise  # 不再 fallback，直接抛出异常
