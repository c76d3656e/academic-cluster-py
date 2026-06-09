"""
写作相关数据模型
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class EvidenceCard(BaseModel):
    """证据卡片"""
    id: str
    paper_id: str
    title: str
    claim: str
    evidence_span: str
    method: Optional[str] = None
    metric: Optional[str] = None
    limitation: Optional[str] = None
    confidence: float = 0.0
    cluster_id: Optional[str] = None


class GapAnalysis(BaseModel):
    """社区差距分析"""
    cluster_id: str
    missing_evidence: list[str] = Field(default_factory=list)
    suggested_queries: list[str] = Field(default_factory=list)
    score: float = 0.0  # 0-1, 越高表示差距越大
    needs_refinement: bool = False


class SectionPlan(BaseModel):
    """章节计划"""
    id: str
    section_number: int
    title: str
    description: str
    key_points: list[str] = Field(default_factory=list)
    cluster_ids: list[str] = Field(default_factory=list)
    target_word_count: int = 1000


class CitationPlan(BaseModel):
    """引用计划"""
    id: str
    section_id: str
    paper_id: str
    citation_text: str
    citation_style: str = "apa"
    relevance_score: float = 0.0
    location_in_section: Optional[str] = None  # 'introduction', 'methodology', 'results', 'discussion'


class WrittenSection(BaseModel):
    """已写章节"""
    id: str
    section_plan_id: str
    content: str
    word_count: int = 0
    quality_score: float = 0.0
    citation_ids: list[str] = Field(default_factory=list)
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class OutlineSection(BaseModel):
    """大纲章节"""
    id: str
    number: int
    title: str
    description: str
    subsections: list["OutlineSection"] = Field(default_factory=list)
    cluster_ids: list[str] = Field(default_factory=list)


class Outline(BaseModel):
    """综述大纲"""
    id: str
    title: str
    abstract: Optional[str] = None
    sections: list[OutlineSection] = Field(default_factory=list)
    status: str = "draft"  # 'draft', 'approved', 'writing', 'completed'
    version: int = 1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class CitationReport(BaseModel):
    """引用报告"""
    total_citations: int = 0
    unique_papers: int = 0
    coverage_by_cluster: dict[str, float] = Field(default_factory=dict)
    invalid_citations: list[str] = Field(default_factory=list)
    assembly_retention: float = 0.0


class ReviewArtifact(BaseModel):
    """综述产出物"""
    id: str
    project_id: str
    outline_id: str
    final_review: str
    bibtex: str
    citation_report: CitationReport
    word_count: int = 0
    quality_score: float = 0.0
    created_at: datetime = Field(default_factory=datetime.utcnow)


# 支持递归引用
OutlineSection.model_rebuild()
