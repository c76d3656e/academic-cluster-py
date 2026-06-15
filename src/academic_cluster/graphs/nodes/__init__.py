"""
图节点模块

每个节点是一个异步函数，接收 PipelineState 并返回状态更新。
"""

# 搜索阶段节点
from .search import search_node
from .deduplicate import deduplicate_node
from .filter import filter_node
from .bm25 import bm25_node

# 嵌入和检索阶段节点
from .embedding import embedding_node
from .pgvector_knn import pgvector_knn_node
from .rerank import rerank_node

# 知识图谱阶段节点
from .kg_extraction import kg_extraction_node

# 聚类阶段节点
from .community_detection import community_detection_node
from .visualize_community import visualize_community_node
from .community_memory import community_memory_node

# 证据阶段节点
from .evidence_cards import evidence_cards_node
from .gap_analysis import gap_analysis_node
from .targeted_refine import targeted_refine_node

# 写作阶段节点
from .outline_generation import outline_generation_node
from .user_confirm import user_confirm_node
from .write_review import write_review_node
from .coverage_audit import coverage_audit_node
from .section_revision import section_revision_node
from .abstract_generation import generate_abstract_node

# 产出阶段节点
from .artifact_registration import artifact_registration_node
from .finalize import finalize_node

__all__ = [
    # 搜索阶段
    "search_node",
    "deduplicate_node",
    "filter_node",
    "bm25_node",
    # 嵌入和检索阶段
    "embedding_node",
    "pgvector_knn_node",
    "rerank_node",
    # 知识图谱阶段
    "kg_extraction_node",
    # 聚类阶段
    "community_detection_node",
    "visualize_community_node",
    "community_memory_node",
    # 证据阶段
    "evidence_cards_node",
    "gap_analysis_node",
    "targeted_refine_node",
    # 写作阶段
    "outline_generation_node",
    "user_confirm_node",
    "write_review_node",
    "coverage_audit_node",
    "section_revision_node",
    "generate_abstract_node",
    # 产出阶段
    "artifact_registration_node",
    "finalize_node",
]
