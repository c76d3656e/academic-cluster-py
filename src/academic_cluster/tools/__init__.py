"""
Tools 模块 - 定义被 Agent 调用的工具

Tool 是确定性函数，执行具体操作（搜索、过滤、存储等）。
与 Agent 不同，Tool 不涉及 LLM 推理。
"""

from .academic_search import (
    search_all_sources,
    search_arxiv,
    search_openalex,
    search_pubmed,
    search_semantic_scholar,
)
from .clustering import (
    build_hybrid_graph,
    community_detection,
    generate_community_visualization,
)
from .text_processing import (
    bm25_search,
    compute_similarity,
    extract_keywords,
)

__all__ = [
    # 文本处理
    "bm25_search",
    # 聚类
    "build_hybrid_graph",
    "community_detection",
    "compute_similarity",
    "extract_keywords",
    "generate_community_visualization",
    "search_all_sources",
    "search_arxiv",
    "search_openalex",
    "search_pubmed",
    # 学术搜索
    "search_semantic_scholar",
]
