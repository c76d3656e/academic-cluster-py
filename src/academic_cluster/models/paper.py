"""
论文相关数据模型
"""

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field


class Paper(BaseModel):
    """论文模型"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    external_id: str | None = None
    source: str  # 'semantic_scholar', 'pubmed', 'arxiv', 'openalex', 'crossref'
    title: str
    abstract: str | None = None
    authors: list[dict] = Field(default_factory=list)
    publication_date: datetime | None = None
    journal: str | None = None
    doi: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    citation_count: int = 0
    reference_count: int = 0
    influential_citation_count: int = 0
    fields_of_study: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)

    # 处理状态
    embedding_id: str | None = None
    quality_score: float | None = None
    rerank_score: float | None = None
    tier: str | None = None  # 'core', 'auxiliary', 'filtered'

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class KGEntity(BaseModel):
    """知识图谱实体"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    entity_type: str  # 'ResearchProblem', 'Method', 'Dataset', 'Metric', 'Material', 'Concept', 'Domain'
    normalized_name: str
    paper_ids: list[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class KGRelation(BaseModel):
    """知识图谱关系"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_entity_id: str
    target_entity_id: str
    relation_type: str  # 'uses', 'evaluated_on', 'improves', 'applied_to', 'based_on', 'proposes', 'compares_with'
    paper_ids: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    metadata: dict = Field(default_factory=dict)


class Embedding(BaseModel):
    """嵌入向量模型"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    paper_id: str
    model_name: str
    vector: list[float] = Field(default_factory=list)
    dimensions: int = 0
    vector_id: str | None = None  # 向量数据库中的 ID
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PaperQuality(BaseModel):
    """论文质量评估"""
    paper_id: str
    jcr_quartile: str | None = None  # 'Q1', 'Q2', 'Q3', 'Q4'
    ccf_rank: str | None = None  # 'A', 'B', 'C'
    impact_factor: float | None = None
    quality_score: float = 0.0
    is_high_quality: bool = False


class RerankResult(BaseModel):
    """重排序结果"""
    paper_id: str
    score: float
    rank: int
    tier: str  # 'core', 'auxiliary'
