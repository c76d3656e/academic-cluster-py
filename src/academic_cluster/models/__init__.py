"""
数据模型模块 - 定义核心数据结构
"""

from .cluster import Cluster, ClusterAssignment
from .paper import Embedding, KGEntity, KGRelation, Paper
from .project import Project, ProjectStatus
from .user import (
    RefreshTokenRequest,
    SystemStatsResponse,
    TokenResponse,
    UserCreate,
    UserListResponse,
    UserLogin,
    UserResponse,
    UserRole,
    UserUpdate,
)
from .writing import CitationPlan, EvidenceCard, Outline, SectionPlan, WrittenSection

__all__ = [
    "CitationPlan",
    "Cluster",
    "ClusterAssignment",
    "Embedding",
    "EvidenceCard",
    "KGEntity",
    "KGRelation",
    "Outline",
    "Paper",
    "Project",
    "ProjectStatus",
    "RefreshTokenRequest",
    "SectionPlan",
    "SystemStatsResponse",
    "TokenResponse",
    "UserCreate",
    "UserListResponse",
    "UserLogin",
    "UserResponse",
    "UserRole",
    "UserUpdate",
    "WrittenSection",
]
