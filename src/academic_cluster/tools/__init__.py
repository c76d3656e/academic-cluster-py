"""
Tools 模块 - 定义被 Agent 调用的工具

Tool 是确定性函数，执行具体操作（搜索、过滤、存储等）。
与 Agent 不同，Tool 不涉及 LLM 推理。
"""

from .academic_search import (
    search_semantic_scholar,
    search_pubmed,
    search_arxiv,
    search_openalex,
    search_all_sources,
)
from .text_processing import (
    bm25_search,
    compute_similarity,
    extract_keywords,
)
from .clustering import (
    build_hybrid_graph,
    community_detection,
    generate_community_visualization,
)

__all__ = [
    # 学术搜索
    "search_semantic_scholar",
    "search_pubmed",
    "search_arxiv",
    "search_openalex",
    "search_all_sources",
    # 文本处理
    "bm25_search",
    "compute_similarity",
    "extract_keywords",
    # 聚类
    "build_hybrid_graph",
    "community_detection",
    "generate_community_visualization",
]
