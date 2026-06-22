"""
FastAPI 依赖注入

提供认证和权限检查的依赖函数。
"""

from typing import Any

import structlog
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from ..services.auth import TokenService, get_token_service
from ..services.database import DatabaseService, get_database

logger = structlog.get_logger()

security = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
    token_service: TokenService = Depends(get_token_service),
    db: DatabaseService = Depends(get_database),
) -> dict[str, Any]:
    """获取当前认证用户"""
    if credentials is None:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    try:
        payload = token_service.decode_access_token(credentials.credentials)
    except ValueError:
        # 安全修复: 不向客户端泄露 JWT 解码的具体错误原因（过期/无效/格式错误）
        raise HTTPException(
            status_code=401, detail="Invalid or expired token"
        ) from None

    user = await db.get_user_by_id(payload["sub"])
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.get("is_active", False):
        raise HTTPException(status_code=401, detail="User account is deactivated")

    return user


async def require_admin(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """要求管理员权限"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
