"""
聚类工具单元测试
"""

import networkx as nx

from academic_cluster.graphs.nodes.community_detection import (
    select_community_balanced_papers,
)
from academic_cluster.tools.clustering import (
    build_hybrid_graph,
    community_detection,
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


class TestCommunityDetection:
    """社区检测测试"""

    def test_fallback_clustering(self):
        """测试备用聚类方法（连通分量）"""
        G = nx.Graph()
        G.add_edges_from(
            [
                ("p1", "p2"),
                ("p2", "p3"),
                ("p3", "p4"),
                ("p5", "p6"),
            ]
        )

        from academic_cluster.tools.clustering import _fallback_clustering

        clusters = _fallback_clustering(G)

        assert len(clusters) == 2  # 应该有两个连通分量
        assert all("id" in c for c in clusters)
        assert all("paper_ids" in c for c in clusters)

    def test_community_detection_leiden(self):
        """测试 Leiden 社区检测"""
        G = nx.Graph()
        # 两个紧密社区
        G.add_edges_from(
            [
                ("p1", "p2", {"weight": 0.9}),
                ("p2", "p3", {"weight": 0.8}),
                ("p3", "p1", {"weight": 0.7}),
                ("p4", "p5", {"weight": 0.9}),
                ("p5", "p6", {"weight": 0.8}),
                ("p6", "p4", {"weight": 0.7}),
                # 弱连接
                ("p3", "p4", {"weight": 0.1}),
            ]
        )

        clusters = community_detection(G, algorithm="leiden")
        assert len(clusters) >= 1
        assert all("id" in c for c in clusters)
        total_papers = sum(c["size"] for c in clusters)
        assert total_papers == 6

    def test_community_detection_walktrap(self):
        """测试 Walktrap 社区检测"""
        G = nx.Graph()
        G.add_edges_from(
            [
                ("p1", "p2", {"weight": 0.9}),
                ("p2", "p3", {"weight": 0.8}),
                ("p4", "p5", {"weight": 0.9}),
                ("p5", "p6", {"weight": 0.8}),
                ("p3", "p4", {"weight": 0.1}),
            ]
        )

        clusters = community_detection(G, algorithm="walktrap")
        assert len(clusters) >= 1
        total_papers = sum(c["size"] for c in clusters)
        assert total_papers == 6

    def test_community_detection_empty_graph(self):
        """测试空图"""
        G = nx.Graph()
        clusters = community_detection(G, algorithm="leiden")
        assert clusters == []


class TestVisualization:
    """可视化测试"""

    def test_generate_visualization(self):
        """测试可视化生成"""
        G = nx.Graph()
        G.add_edges_from(
            [
                ("p1", "p2", {"weight": 0.8}),
                ("p2", "p3", {"weight": 0.6}),
            ]
        )

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


def test_select_community_balanced_papers_exact_160_and_covers_clusters():
    papers = [
        {
            "id": f"p{i}",
            "title": f"Paper {i}",
            "abstract": "abstract",
            "citation_count": 240 - i,
            "publication_date": "2024-01-01",
        }
        for i in range(240)
    ]
    clusters = [
        {"id": "c1", "paper_ids": [f"p{i}" for i in range(120)]},
        {"id": "c2", "paper_ids": [f"p{i}" for i in range(120, 180)]},
        {"id": "c3", "paper_ids": [f"p{i}" for i in range(180, 240)]},
    ]

    core, auxiliary = select_community_balanced_papers(
        clusters=clusters,
        reranked_papers=papers,
        core_count=160,
        auxiliary_count=40,
    )

    assert len(core) == 160
    assert len(set(core)) == 160
    assert len(auxiliary) == 40
    for cluster in clusters:
        assert set(core) & set(cluster["paper_ids"])


def test_generate_visualization_uses_checkpoint_safe_scalar_types():
    import numpy as np

    G = nx.Graph()
    G.add_edge("p1", "p2", weight=np.float64(0.8))
    clusters = [{"id": "cluster_1", "paper_ids": ["p1", "p2"], "size": np.int64(2)}]
    papers = [
        {"id": "p1", "title": "Paper 1", "citation_count": np.int64(4)},
        {"id": "p2", "title": "Paper 2", "citation_count": np.int64(1)},
    ]

    visualization = generate_community_visualization(G, clusters, papers)

    def assert_plain_scalars(value):
        if isinstance(value, dict):
            for nested in value.values():
                assert_plain_scalars(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_plain_scalars(nested)
        else:
            assert not isinstance(value, np.generic)
            assert not isinstance(value, np.ndarray)

    assert_plain_scalars(visualization)
