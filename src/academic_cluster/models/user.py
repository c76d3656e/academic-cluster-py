"""
用户和认证相关的 Pydantic 模型
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class UserRole(StrEnum):
    """用户角色"""

    USER = "user"
    ADMIN = "admin"


class UserCreate(BaseModel):
    """用户注册请求"""

    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(None, max_length=255)


class UserLogin(BaseModel):
    """用户登录请求"""

    email: str
    password: str


class UserUpdate(BaseModel):
    """用户信息更新请求"""

    full_name: str | None = Field(None, max_length=255)
    password: str | None = Field(None, min_length=8, max_length=128)


class UserResponse(BaseModel):
    """用户信息响应"""

    id: str
    email: str
    full_name: str | None = None
    role: str = "user"
    is_active: bool = True
    created_at: datetime | None = None


class TokenResponse(BaseModel):
    """Token 响应"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    """刷新 Token 请求"""

    refresh_token: str


class UserListResponse(BaseModel):
    """用户列表响应"""

    users: list[UserResponse]
    total: int


class SystemStatsResponse(BaseModel):
    """系统统计响应"""

    total_users: int
    total_projects: int
    total_papers: int
    active_users: int
