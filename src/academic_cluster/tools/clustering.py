"""
聚类工具

实现混合图构建、社区检测（Leiden / Walktrap）、可视化生成等功能。
"""

import math
import uuid
from collections import defaultdict
from typing import Optional

import networkx as nx
import structlog

logger = structlog.get_logger()


def _plain_float(value, default: float = 0.0) -> float:
    """Return a checkpoint-safe Python float from numpy or numeric values."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _plain_int(value, default: int = 0) -> int:
    """Return a checkpoint-safe Python int from numpy or numeric values."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# =============================================================================
# 混合图构建
# =============================================================================

def build_hybrid_graph(
    knn_edges: list[dict],
    kg_relations: list[dict],
    kg_entities: list[dict],
    evidence_cards: list[dict],
    core_paper_ids: list[str],
    weights: Optional[dict[str, float]] = None,
) -> nx.Graph:
    """
    构建混合图

    融合 5 种边信号：
    1. Vector KNN (weight: 0.45) - 向量相似度边
    2. KG Relation (weight: 0.25) - 知识图谱关系边
    3. Shared Entity (weight: 0.15) - 共享实体边
    4. Evidence (weight: 0.10) - 共享证据边
    5. Quality Prior (weight: 0.05) - 高质量论文对

    Args:
        knn_edges: KNN 图边列表 [{source, target, weight}]
        kg_relations: 知识图谱关系列表 [{source_entity, target_entity, paper_ids}]
        kg_entities: 知识图谱实体列表 [{id, name, paper_ids}]
        evidence_cards: 证据卡片列表 [{paper_id, ...}]
        core_paper_ids: 核心论文 ID 列表
        weights: 各信号权重

    Returns:
        NetworkX 图
    """
    knn_edges = knn_edges or []
    kg_relations = kg_relations or []
    kg_entities = kg_entities or []
    evidence_cards = evidence_cards or []
    core_paper_ids = core_paper_ids or []

    if weights is None:
        weights = {
            "knn": 0.45,
            "kg_relation": 0.25,
            "shared_entity": 0.15,
            "evidence": 0.10,
            "quality": 0.05,
        }

    G = nx.Graph()

    # 添加所有核心论文作为节点
    for paper_id in core_paper_ids:
        G.add_node(paper_id, is_core=True)

    # 1. 添加 KNN 边
    for edge in knn_edges:
        source = edge.get("source")
        target = edge.get("target")
        weight = edge.get("weight", 0.0) * weights["knn"]

        if G.has_node(source) and G.has_node(target):
            if G.has_edge(source, target):
                G[source][target]["weight"] += weight
            else:
                G.add_edge(source, target, weight=weight, types=["knn"])

    # 2. 添加 KG 关系边
    for relation in kg_relations:
        source_entity = relation.get("source_entity")
        target_entity = relation.get("target_entity")
        paper_ids = relation.get("paper_ids") or []

        # 通过共享关系连接论文
        for i, paper_a in enumerate(paper_ids):
            for paper_b in paper_ids[i + 1:]:
                if G.has_node(paper_a) and G.has_node(paper_b):
                    weight = weights["kg_relation"]
                    if G.has_edge(paper_a, paper_b):
                        G[paper_a][paper_b]["weight"] += weight
                    else:
                        G.add_edge(paper_a, paper_b, weight=weight, types=["kg_relation"])

    # 3. 添加共享实体边
    entity_to_papers = defaultdict(list)
    for entity in kg_entities:
        entity_id = entity.get("id")
        for paper_id in entity.get("paper_ids") or []:
            entity_to_papers[entity_id].append(paper_id)

    # 实体类型权重
    entity_type_weights = {
        "ResearchProblem": 1.0,
        "Method": 1.0,
        "Dataset": 1.0,
        "Metric": 1.0,
        "Material": 1.0,
        "Concept": 0.8,
        "Domain": 0.8,
    }

    for entity in kg_entities:
        entity_type = entity.get("type", "Concept")
        type_weight = entity_type_weights.get(entity_type, 0.8)
        paper_ids = entity.get("paper_ids") or []

        for i, paper_a in enumerate(paper_ids):
            for paper_b in paper_ids[i + 1:]:
                if G.has_node(paper_a) and G.has_node(paper_b):
                    weight = weights["shared_entity"] * type_weight
                    if G.has_edge(paper_a, paper_b):
                        G[paper_a][paper_b]["weight"] += weight
                    else:
                        G.add_edge(paper_a, paper_b, weight=weight, types=["shared_entity"])

    # 4. 添加证据边
    evidence_to_papers = defaultdict(list)
    for card in evidence_cards:
        paper_id = card.get("paper_id")
        # 使用 claim 的前 50 字符作为证据标识
        evidence_key = card.get("claim", "")[:50]
        if paper_id:
            evidence_to_papers[evidence_key].append(paper_id)

    for evidence_key, paper_ids in evidence_to_papers.items():
        for i, paper_a in enumerate(paper_ids):
            for paper_b in paper_ids[i + 1:]:
                if G.has_node(paper_a) and G.has_node(paper_b):
                    weight = weights["evidence"]
                    if G.has_edge(paper_a, paper_b):
                        G[paper_a][paper_b]["weight"] += weight
                    else:
                        G.add_edge(paper_a, paper_b, weight=weight, types=["evidence"])

    # 5. 质量先验（核心论文之间的边）
    for i, paper_a in enumerate(core_paper_ids[:20]):  # Top 20 核心论文
        for paper_b in core_paper_ids[i + 1:20]:
            if G.has_node(paper_a) and G.has_node(paper_b):
                weight = weights["quality"]
                if G.has_edge(paper_a, paper_b):
                    G[paper_a][paper_b]["weight"] += weight
                else:
                    G.add_edge(paper_a, paper_b, weight=weight, types=["quality"])

    logger.info(
        "Hybrid graph built",
        nodes=G.number_of_nodes(),
        edges=G.number_of_edges(),
    )

    return G


# =============================================================================
# 社区检测（igraph 原生 API，支持 Leiden / Walktrap）
# =============================================================================

def community_detection(
    graph: nx.Graph,
    algorithm: str = "leiden",
    resolution: float = 1.0,
    seed: int = 42,
    max_iterations: int = 100,
) -> list[dict]:
    """
    社区检测入口，支持多种算法。

    Args:
        graph: NetworkX 图
        algorithm: "leiden" 或 "walktrap"
        resolution: 分辨率参数（仅 leiden 有效），越大社区越多
        seed: 随机种子（仅 leiden 有效）
        max_iterations: 最大迭代次数（仅 leiden 有效）

    Returns:
        聚类列表 [{id, paper_ids, size}]
    """
    if graph.number_of_nodes() == 0:
        return []

    if graph.number_of_edges() == 0:
        return _fallback_clustering(graph)

    try:
        import igraph as ig
    except ModuleNotFoundError:
        logger.warning("igraph unavailable, using NetworkX fallback clustering")
        return _fallback_clustering(graph)

    # 转换为 igraph 格式
    nodes = list(graph.nodes())
    node_to_idx = {node: i for i, node in enumerate(nodes)}

    edges = []
    weights = []
    for u, v, data in graph.edges(data=True):
        edges.append((node_to_idx[u], node_to_idx[v]))
        weights.append(data.get("weight", 1.0))

    ig_graph = ig.Graph(n=len(nodes), edges=edges, directed=False)
    ig_graph.es["weight"] = weights

    algo = algorithm.lower().strip()

    if algo == "walktrap":
        clusters = _run_walktrap(ig_graph, nodes)
    else:
        clusters = _run_leiden(ig_graph, nodes, resolution, seed, max_iterations)

    logger.info(
        "Community detection completed",
        algorithm=algo,
        clusters=len(clusters),
        total_nodes=len(nodes),
    )

    return clusters


def _run_leiden(
    ig_graph,
    nodes: list,
    resolution: float,
    seed: int,
    max_iterations: int,
) -> list[dict]:
    """igraph 原生 Leiden 社区检测。"""
    partition = ig_graph.community_leiden(
        objective_function="modularity",
        weights="weight",
        resolution=resolution,
        beta=0.01,
        n_iterations=max_iterations,
    )

    clusters = []
    for i, cluster_nodes in enumerate(partition):
        paper_ids = [nodes[idx] for idx in cluster_nodes]
        clusters.append({
            "id": str(uuid.uuid4()),
            "name": f"cluster_{i}",
            "paper_ids": paper_ids,
            "size": len(paper_ids),
        })
    return clusters


def _run_walktrap(ig_graph, nodes: list) -> list[dict]:
    """igraph 原生 Walktrap 社区检测。"""
    dendrogram = ig_graph.community_walktrap(weights="weight")
    partition = dendrogram.as_clustering()

    clusters = []
    for i, cluster_nodes in enumerate(partition):
        paper_ids = [nodes[idx] for idx in cluster_nodes]
        clusters.append({
            "id": str(uuid.uuid4()),
            "name": f"cluster_{i}",
            "paper_ids": paper_ids,
            "size": len(paper_ids),
        })
    return clusters


def _fallback_clustering(graph: nx.Graph) -> list[dict]:
    """备用聚类：连通分量（无边或 igraph 不可用时使用）。"""
    clusters = []
    for i, component in enumerate(nx.connected_components(graph)):
        clusters.append({
            "id": str(uuid.uuid4()),
            "name": f"cluster_{i}",
            "paper_ids": list(component),
            "size": len(component),
        })
    return clusters


# =============================================================================
# 可视化生成
# =============================================================================

def generate_community_visualization(
    graph: nx.Graph,
    clusters: list[dict],
    papers: list[dict],
    layout: str = "force",
) -> dict:
    """
    生成社区可视化数据

    Args:
        graph: 混合图
        clusters: 聚类列表
        papers: 论文列表
        layout: 布局算法 (force, circular, spring)

    Returns:
        可视化数据 {nodes, edges, clusters}
    """
    # 创建论文 ID 到聚类的映射
    paper_to_cluster = {}
    for cluster in clusters:
        for paper_id in cluster.get("paper_ids") or []:
            paper_to_cluster[paper_id] = cluster["id"]

    # 创建论文 ID 到论文的映射
    paper_map = {p.get("id"): p for p in papers}

    # 生成颜色
    cluster_colors = _generate_colors(len(clusters))
    cluster_color_map = {
        cluster["id"]: cluster_colors[i]
        for i, cluster in enumerate(clusters)
    }

    # 计算布局
    if graph.number_of_nodes() == 0:
        pos = {}
    elif layout == "force":
        pos = nx.spring_layout(graph, k=1/math.sqrt(graph.number_of_nodes()), iterations=50)
    elif layout == "circular":
        pos = nx.circular_layout(graph)
    else:
        pos = nx.spring_layout(graph)

    # 生成节点数据
    nodes = []
    for node_id in graph.nodes():
        paper = paper_map.get(node_id, {})
        cluster_id = paper_to_cluster.get(node_id, "unknown")

        nodes.append({
            "id": node_id,
            "label": paper.get("title", "")[:50],
            "x": _plain_float(pos[node_id][0]) if node_id in pos else 0.0,
            "y": _plain_float(pos[node_id][1]) if node_id in pos else 0.0,
            "cluster": cluster_id,
            "color": cluster_color_map.get(cluster_id, "#999999"),
            "size": _plain_float(math.log(paper.get("citation_count", 0) + 1) * 3 + 5),
            "title": paper.get("title", ""),
            "citation_count": _plain_int(paper.get("citation_count", 0)),
        })

    # 生成边数据
    edges = []
    for u, v, data in graph.edges(data=True):
        weight = data.get("weight", 0.0)
        if weight > 0.05:  # 只显示权重较大的边
            edges.append({
                "source": u,
                "target": v,
                "weight": _plain_float(weight),
                "width": _plain_float(weight * 3),
            })

    # 生成聚类摘要
    cluster_summaries = []
    for cluster in clusters:
        cluster_papers = [
            paper_map.get(pid, {})
            for pid in cluster.get("paper_ids") or []
        ]

        cluster_summaries.append({
            "id": cluster["id"],
            "size": _plain_int(cluster["size"]),
            "color": cluster_color_map.get(cluster["id"], "#999999"),
            "papers": [
                {
                    "id": p.get("id"),
                    "title": p.get("title", "")[:80],
                }
                for p in cluster_papers[:5]  # 只显示前 5 篇
            ],
        })

    visualization = {
        "nodes": nodes,
        "edges": edges,
        "clusters": cluster_summaries,
        "layout": layout,
        "metadata": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "total_clusters": len(clusters),
        },
    }

    logger.info(
        "Community visualization generated",
        nodes=len(nodes),
        edges=len(edges),
        clusters=len(clusters),
    )

    return visualization


def _generate_colors(n: int) -> list[str]:
    """生成 N 个不同的颜色"""
    colors = [
        "#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7",
        "#DDA0DD", "#98D8C8", "#F7DC6F", "#BB8FCE", "#85C1E9",
        "#F8C471", "#82E0AA", "#F1948A", "#AED6F1", "#D7BDE2",
        "#A3E4D7", "#FAD7A0", "#D5F5E3", "#FADBD8", "#D4E6F1",
    ]

    if n <= len(colors):
        return colors[:n]

    # 生成更多颜色
    import colorsys
    extra_colors = []
    for i in range(n - len(colors)):
        hue = i / (n - len(colors))
        r, g, b = colorsys.hsv_to_rgb(hue, 0.7, 0.9)
        extra_colors.append(f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}")

    return colors + extra_colors
