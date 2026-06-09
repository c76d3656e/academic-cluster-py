"""
聚类工具单元测试
"""

import pytest
import networkx as nx

from academic_cluster.tools.clustering import (
    build_hybrid_graph,
    leiden_clustering,
    generate_community_visualization,
)


class TestHybridGraph:
    """混合图构建测试"""

    def test_build_hybrid_graph(self):
        """测试混合图构建"""
        knn_edges = [
            {"source": "p1", "target": "p2", "weight": 0.8},
            {"source": "p2", "target": "p3", "weight": 0.7},
        ]

        kg_relations = [
            {
                "source_entity": "method_a",
                "target_entity": "dataset_b",
                "paper_ids": ["p1", "p2"],
            },
        ]

        kg_entities = [
            {
                "id": "method_a",
                "name": "Method A",
                "type": "Method",
                "paper_ids": ["p1", "p2"],
            },
        ]

        evidence_cards = [
            {"paper_id": "p1", "claim": "Claim 1"},
            {"paper_id": "p2", "claim": "Claim 1"},
        ]

        core_paper_ids = ["p1", "p2", "p3"]

        graph = build_hybrid_graph(
            knn_edges=knn_edges,
            kg_relations=kg_relations,
            kg_entities=kg_entities,
            evidence_cards=evidence_cards,
            core_paper_ids=core_paper_ids,
        )

        assert isinstance(graph, nx.Graph)
        assert graph.number_of_nodes() == 3
        assert graph.number_of_edges() > 0

    def test_graph_weights(self):
        """测试边权重"""
        knn_edges = [
            {"source": "p1", "target": "p2", "weight": 1.0},
        ]

        graph = build_hybrid_graph(
            knn_edges=knn_edges,
            kg_relations=[],
            kg_entities=[],
            evidence_cards=[],
            core_paper_ids=["p1", "p2"],
        )

        # 检查边权重
        assert graph.has_edge("p1", "p2")
        assert graph["p1"]["p2"]["weight"] > 0


class TestLeidenClustering:
    """Leiden 聚类测试"""

    def test_fallback_clustering(self):
        """测试备用聚类方法"""
        # 创建一个简单的图
        G = nx.Graph()
        G.add_edges_from([
            ("p1", "p2"),
            ("p2", "p3"),
            ("p3", "p4"),
            ("p5", "p6"),
        ])

        # 使用备用方法（不依赖 leidenalg）
        from academic_cluster.tools.clustering import _fallback_clustering
        clusters = _fallback_clustering(G)

        assert len(clusters) == 2  # 应该有两个连通分量
        assert all("id" in c for c in clusters)
        assert all("paper_ids" in c for c in clusters)


class TestVisualization:
    """可视化测试"""

    def test_generate_visualization(self):
        """测试可视化生成"""
        G = nx.Graph()
        G.add_edges_from([
            ("p1", "p2", {"weight": 0.8}),
            ("p2", "p3", {"weight": 0.6}),
        ])

        clusters = [
            {"id": "cluster_0", "paper_ids": ["p1", "p2"], "size": 2},
            {"id": "cluster_1", "paper_ids": ["p3"], "size": 1},
        ]

        papers = [
            {"id": "p1", "title": "Paper 1", "citation_count": 10},
            {"id": "p2", "title": "Paper 2", "citation_count": 5},
            {"id": "p3", "title": "Paper 3", "citation_count": 3},
        ]

        viz = generate_community_visualization(G, clusters, papers)

        assert "nodes" in viz
        assert "edges" in viz
        assert "clusters" in viz
        assert len(viz["nodes"]) == 3
        assert len(viz["clusters"]) == 2
