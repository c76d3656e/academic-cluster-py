"""
用户和认证相关的 Pydantic 模型
"""

import enum
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRole(enum.StrEnum):
    """用户角色"""

    USER = "user"
    ADMIN = "admin"


class UserCreate(BaseModel):
    """用户注册请求"""

    email: EmailStr = Field(..., max_length=255)
    password: str = Field(..., min_length=12, max_length=128)
    full_name: str | None = Field(None, max_length=255)


class UserLogin(BaseModel):
    """用户登录请求"""

    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    """用户信息更新请求"""

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = Field(None, max_length=255)


class UserResponse(BaseModel):
    """用户信息响应"""

    id: str
    email: EmailStr
    full_name: str | None = None
    role: str = "user"
    is_active: bool = True
    created_at: datetime | None = None


class TokenResponse(BaseModel):
    """Token 响应"""

    access_token: str
    token_type: str = "bearer"


class RefreshTokenRequest(BaseModel):
    """刷新 Token 请求"""

    refresh_token: str


class UserListResponse(BaseModel):
    """管理员用户列表响应。"""

    users: list[UserResponse]
    total: int
