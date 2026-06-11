"""
LangGraph 状态定义

定义在图节点间传递的状态结构。
状态应该只包含引用 ID，大型数据存储在外部数据库中。
"""

from operator import add
from typing import Annotated, Any, Optional

from langgraph.graph import add_messages
from pydantic import BaseModel, Field


class PipelineState(BaseModel):
    """
    主 Pipeline 状态

    设计原则：
    - 大型数据（论文详情、嵌入向量）存储在外部数据库，状态中只保留 ID
    - 使用 Annotated 支持状态的追加操作
    - 保持状态轻量，便于序列化和检查点
    """

    # === 元数据 ===
    project_id: str
    query: str
    status: str = "created"
    current_node: Optional[str] = None
    errors: Annotated[list[str], add] = Field(default_factory=list)
    retry_count: int = 0

    # === 搜索阶段 ===
    # 论文 ID 列表（详情存储在 PostgreSQL）
    paper_ids: Annotated[list[str], add] = Field(default_factory=list)
    total_searched: int = 0

    # === 过滤阶段 ===
    filtered_paper_ids: list[str] = Field(default_factory=list)
    core_paper_ids: list[str] = Field(default_factory=list)
    auxiliary_paper_ids: list[str] = Field(default_factory=list)

    # === 嵌入阶段 ===
    # 嵌入向量 ID 列表（向量存储在向量数据库）
    embedding_ids: list[str] = Field(default_factory=list)
    knn_graph_id: Optional[str] = None  # KNN 图在数据库中的 ID

    # === 知识图谱阶段 ===
    kg_entity_ids: list[str] = Field(default_factory=list)
    kg_relation_ids: list[str] = Field(default_factory=list)

    # === 聚类阶段 ===
    cluster_ids: list[str] = Field(default_factory=list)
    hybrid_graph_id: Optional[str] = None
    community_visualization: Optional[dict] = None  # 推送给前端的可视化数据

    # === 证据阶段 ===
    evidence_card_ids: list[str] = Field(default_factory=list)
    gap_analysis_ids: list[str] = Field(default_factory=list)
    needs_targeted_refinement: bool = False
    refinement_attempt: int = 0
    max_refinement_attempts: int = 2

    # === 写作阶段 ===
    outline_id: Optional[str] = None
    outline_data: Optional[dict] = None  # 大纲内容（用于 write_review 节点）
    section_plan_ids: list[str] = Field(default_factory=list)
    citation_plan_ids: list[str] = Field(default_factory=list)
    written_section_ids: list[str] = Field(default_factory=list)

    # === 产出物 ===
    final_review_id: Optional[str] = None
    final_review: Optional[str] = None  # 最终综述内容
    bibtex: Optional[str] = None
    artifact_id: Optional[str] = None

    # === 覆盖审计 ===
    coverage_score: float = 0.0
    invalid_citation_count: int = 0
    needs_revision: bool = False

    # === 配置 ===
    config: dict = Field(default_factory=dict)

    class Config:
        """Pydantic 配置"""
        arbitrary_types_allowed = True


class SearchState(BaseModel):
    """搜索子图状态"""
    query: str
    source: str
    raw_results: list[dict] = Field(default_factory=list)
    processed_ids: list[str] = Field(default_factory=list)
    error: Optional[str] = None


class ClusteringState(BaseModel):
    """聚类子图状态"""
    paper_ids: list[str] = Field(default_factory=list)
    embedding_ids: list[str] = Field(default_factory=list)
    kg_entity_ids: list[str] = Field(default_factory=list)
    kg_relation_ids: list[str] = Field(default_factory=list)
    evidence_card_ids: list[str] = Field(default_factory=list)

    hybrid_graph_id: Optional[str] = None
    cluster_ids: list[str] = Field(default_factory=list)
    visualization: Optional[dict] = None


class WritingState(BaseModel):
    """写作子图状态"""
    outline_id: Optional[str] = None
    cluster_ids: list[str] = Field(default_factory=list)
    evidence_card_ids: list[str] = Field(default_factory=list)
    core_paper_ids: list[str] = Field(default_factory=list)

    section_plan_ids: list[str] = Field(default_factory=list)
    citation_plan_ids: list[str] = Field(default_factory=list)
    written_section_ids: list[str] = Field(default_factory=list)

    final_review: Optional[str] = None
    bibtex: Optional[str] = None

    # 覆盖审计
    coverage_score: float = 0.0
    invalid_citation_count: int = 0
    needs_revision: bool = False
