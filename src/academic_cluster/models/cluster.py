"""
聚类相关数据模型
"""

from datetime import datetime

from pydantic import BaseModel, Field


class Cluster(BaseModel):
    """聚类/社区模型"""

    id: str
    name: str | None = None
    description: str | None = None
    algorithm: str = "leiden"
    parameters: dict = Field(default_factory=dict)
    quality_score: float = 0.0
    size: int = 0
    paper_ids: list[str] = Field(default_factory=list)

    # 社区特征
    main_topics: list[str] = Field(default_factory=list)
    key_entities: list[str] = Field(default_factory=list)
    representative_paper_id: str | None = None

    created_at: datetime = Field(default_factory=datetime.utcnow)


class ClusterAssignment(BaseModel):
    """聚类分配"""

    id: str
    cluster_id: str
    paper_id: str
    confidence: float = 1.0
    is_representative: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)


class HybridGraphEdge(BaseModel):
    """混合图边"""

    source_paper_id: str
    target_paper_id: str
    edge_type: str  # 'knn', 'kg_relation', 'shared_entity', 'evidence', 'quality'
    weight: float = 0.0
    metadata: dict = Field(default_factory=dict)


class HybridGraph(BaseModel):
    """混合图"""

    edges: list[HybridGraphEdge] = Field(default_factory=list)
    weights: dict = Field(
        default_factory=lambda: {
            "knn": 0.45,
            "kg_relation": 0.25,
            "shared_entity": 0.15,
            "evidence": 0.10,
            "quality": 0.05,
        }
    )
    adjacency: dict[str, dict[str, float]] = Field(default_factory=dict)

    def add_edge(self, edge: HybridGraphEdge):
        """添加边到图"""
        self.edges.append(edge)

        # 更新邻接表
        if edge.source_paper_id not in self.adjacency:
            self.adjacency[edge.source_paper_id] = {}
        if edge.target_paper_id not in self.adjacency:
            self.adjacency[edge.target_paper_id] = {}

        self.adjacency[edge.source_paper_id][edge.target_paper_id] = edge.weight
        self.adjacency[edge.target_paper_id][edge.source_paper_id] = edge.weight


class CommunityVisualization(BaseModel):
    """社区可视化数据"""

    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    clusters: list[dict] = Field(default_factory=list)
    layout: str = "force"  # 'force', 'circular', 'hierarchical'
    metadata: dict = Field(default_factory=dict)
