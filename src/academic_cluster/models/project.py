"""
项目相关数据模型
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ProjectStatus(StrEnum):
    """项目状态枚举"""

    CREATED = "created"
    SEARCHING = "searching"
    FILTERING = "filtering"
    EMBEDDING = "embedding"
    CLUSTERING = "clustering"
    EXTRACTING_KG = "extracting_kg"
    GENERATING_EVIDENCE = "generating_evidence"
    ANALYZING_GAPS = "analyzing_gaps"
    OUTLINING = "outlining"
    CONFIRMING_OUTLINE = "confirming_outline"
    WRITING = "writing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"


class ProjectConfig(BaseModel):
    """项目配置"""

    # 搜索配置
    max_papers: int = 500
    sources: list[str] = Field(
        default_factory=lambda: ["semantic_scholar", "pubmed", "arxiv"]
    )

    # 质量过滤
    min_citation_count: int = 0
    min_year: int | None = None
    jcr_quartiles: list[str] = Field(default_factory=lambda: ["Q1", "Q2"])

    # 聚类配置
    clustering_algorithm: str = "leiden"
    clustering_resolution: float = 1.0

    # 写作配置
    writing_model: str = "gpt-4o"
    writing_temperature: float = 0.7
    max_review_length: int = 50000
    citation_style: str = "apa"

    # 参考论文数量
    core_reference_count: int = 160
    auxiliary_reference_count: int = 160


class Project(BaseModel):
    """项目模型"""

    id: str
    name: str
    description: str | None = None
    query: str
    status: ProjectStatus = ProjectStatus.CREATED
    config: ProjectConfig = Field(default_factory=ProjectConfig)

    # 统计信息
    paper_count: int = 0
    cluster_count: int = 0
    citation_count: int = 0
    word_count: int = 0

    # 时间戳
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    # 错误信息
    error_message: str | None = None
    retry_count: int = 0
