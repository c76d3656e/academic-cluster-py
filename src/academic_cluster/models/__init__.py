"""
数据模型模块 - 定义核心数据结构
"""

from .paper import Paper, KGEntity, KGRelation, Embedding
from .cluster import Cluster, ClusterAssignment
from .writing import Outline, SectionPlan, CitationPlan, WrittenSection, EvidenceCard
from .project import Project, ProjectStatus
from .user import (
    UserRole,
    UserCreate,
    UserLogin,
    UserUpdate,
    UserResponse,
    TokenResponse,
    RefreshTokenRequest,
    UserListResponse,
    SystemStatsResponse,
)

__all__ = [
    "Paper",
    "KGEntity",
    "KGRelation",
    "Embedding",
    "Cluster",
    "ClusterAssignment",
    "Outline",
    "SectionPlan",
    "CitationPlan",
    "WrittenSection",
    "EvidenceCard",
    "Project",
    "ProjectStatus",
    "UserRole",
    "UserCreate",
    "UserLogin",
    "UserUpdate",
    "UserResponse",
    "TokenResponse",
    "RefreshTokenRequest",
    "UserListResponse",
    "SystemStatsResponse",
]
