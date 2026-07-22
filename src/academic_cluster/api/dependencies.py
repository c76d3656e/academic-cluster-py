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
from ..services.tenant_context import set_tenant_context

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

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    user = await db.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")

    if not user.get("is_active", False):
        raise HTTPException(status_code=401, detail="User account is deactivated")

    request_headers = getattr(request, "headers", {})
    requested_organization = request_headers.get("X-Organization-ID")
    organization_id = requested_organization or user.get("default_organization_id")
    set_tenant_context(
        user_id=user_id,
        organization_id=str(organization_id) if organization_id else None,
        is_admin=user.get("role") == "admin",
    )
    if requested_organization and not await db.user_has_organization_access(
        user_id, requested_organization
    ):
        raise HTTPException(status_code=403, detail="Organization access denied")
    user["active_organization_id"] = organization_id

    return user


def project_access_allowed(project: dict[str, Any], user: dict[str, Any]) -> bool:
    """Apply active-tenant access with a legacy owner fallback during migration."""
    if user.get("role") == "admin":
        return True
    organization_id = project.get("organization_id")
    if organization_id:
        return str(organization_id) == str(user.get("active_organization_id"))
    return str(project.get("user_id")) == str(user.get("id"))


async def require_admin(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """要求管理员权限"""
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
