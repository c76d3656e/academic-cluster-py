"""
认证 API 路由

提供用户注册、登录、Token 刷新、用户管理等端点。
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request

from ..config import get_settings
from ..models.user import (
    RefreshTokenRequest,
    SystemStatsResponse,
    TokenResponse,
    UserCreate,
    UserListResponse,
    UserLogin,
    UserResponse,
    UserUpdate,
)
from ..services.auth import (
    PasswordService,
    TokenService,
    get_password_service,
    get_token_service,
)
from ..services.database import DatabaseService, get_database
from .dependencies import get_current_user, require_admin

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

# TODO[LOW]: 添加 API 速率限制中间件（如 slowapi），防止暴力破解和滥用
# 建议: /auth/login 限制 5 次/分钟，/auth/register 限制 3 次/分钟


# =============================================================================
# 公开端点
# =============================================================================


@router.post("/register", response_model=UserResponse)
async def register(
    body: UserCreate,
    request: Request,
    db: DatabaseService = Depends(get_database),
    password_service: PasswordService = Depends(get_password_service),
) -> UserResponse:
    """用户注册"""
    existing = await db.get_user_by_email(body.email)
    if existing:
        # 安全修复: 使用模糊错误信息，防止用户枚举攻击
        raise HTTPException(status_code=400, detail="注册失败，请稍后重试")

    hashed_password = password_service.hash_password(body.password)

    user_id = await db.save_user(
        {
            "email": body.email,
            "hashed_password": hashed_password,
            "full_name": body.full_name,
            "role": "user",
            "is_active": True,
        }
    )

    await db.log_activity(
        user_id, "register", ip_address=request.client.host if request.client else None
    )

    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=500, detail="Failed to retrieve created user")
    logger.info("User registered", user_id=user_id, email=body.email)

    return UserResponse(
        id=user["id"],
        email=user["email"],
        full_name=user.get("full_name"),
        role=user["role"],
        is_active=user["is_active"],
        created_at=user.get("created_at"),
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: UserLogin,
    request: Request,
    db: DatabaseService = Depends(get_database),
    password_service: PasswordService = Depends(get_password_service),
    token_service: TokenService = Depends(get_token_service),
) -> TokenResponse:
    """用户登录"""
    user = await db.get_user_by_email(body.email)
    if not user:
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    if not password_service.verify_password(body.password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")

    if not user.get("is_active", False):
        raise HTTPException(status_code=401, detail="账号已被停用")

    # 检查是否需要重新哈希
    if password_service.needs_rehash(user["hashed_password"]):
        new_hash = password_service.hash_password(body.password)
        await db.update_user(user["id"], {"hashed_password": new_hash})

    # 创建 Token
    access_token = token_service.create_access_token(user["id"], user["role"])
    raw_refresh_token, token_hash = token_service.create_refresh_token(user["id"])

    # 存储 Refresh Token
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    await db.save_refresh_token(token_hash, user["id"], expires_at)

    # 更新最后登录时间
    await db.update_user(user["id"], {"last_login_at": datetime.now(UTC)})

    await db.log_activity(
        user["id"], "login", ip_address=request.client.host if request.client else None
    )

    logger.info("User logged in", user_id=user["id"], email=body.email)

    return TokenResponse(
        access_token=access_token,
        refresh_token=raw_refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshTokenRequest,
    db: DatabaseService = Depends(get_database),
    token_service: TokenService = Depends(get_token_service),
) -> TokenResponse:
    """刷新 Access Token"""
    token_hash = token_service.hash_refresh_token(body.refresh_token)

    stored_token = await db.get_refresh_token(token_hash)
    if not stored_token:
        raise HTTPException(status_code=401, detail="无效或已过期的 Refresh Token")

    # 撤销旧 Token (Rotation)
    await db.revoke_refresh_token(token_hash)

    # 获取用户信息
    user = await db.get_user_by_id(stored_token["user_id"])
    if not user or not user.get("is_active", False):
        raise HTTPException(status_code=401, detail="用户不存在或已被停用")

    # 创建新 Token
    access_token = token_service.create_access_token(user["id"], user["role"])
    new_raw_token, new_token_hash = token_service.create_refresh_token(user["id"])

    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    await db.save_refresh_token(new_token_hash, user["id"], expires_at)

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_raw_token,
    )


# =============================================================================
# 需要认证的端点
# =============================================================================


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> UserResponse:
    """获取当前用户信息"""
    return UserResponse(
        id=current_user["id"],
        email=current_user["email"],
        full_name=current_user.get("full_name"),
        role=current_user["role"],
        is_active=current_user["is_active"],
        created_at=current_user.get("created_at"),
    )


@router.put("/me", response_model=UserResponse)
async def update_me(
    body: UserUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
    password_service: PasswordService = Depends(get_password_service),
) -> UserResponse:
    """更新当前用户信息"""
    update_data = {}

    if body.full_name is not None:
        update_data["full_name"] = body.full_name

    if body.password is not None:
        update_data["hashed_password"] = password_service.hash_password(body.password)

    if update_data:
        await db.update_user(current_user["id"], update_data)

    user = await db.get_user_by_id(current_user["id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(
        id=user["id"],
        email=user["email"],
        full_name=user.get("full_name"),
        role=user["role"],
        is_active=user["is_active"],
        created_at=user.get("created_at"),
    )


@router.post("/logout")
async def logout(
    body: RefreshTokenRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
    token_service: TokenService = Depends(get_token_service),
) -> dict[str, str]:
    """用户登出"""
    token_hash = token_service.hash_refresh_token(body.refresh_token)
    await db.revoke_refresh_token(token_hash)
    await db.log_activity(current_user["id"], "logout")

    return {"message": "登出成功"}


# =============================================================================
# 管理员端点
# =============================================================================


@router.get("/users", response_model=UserListResponse)
async def list_users(
    skip: int = 0,
    limit: int = 20,
    admin: dict[str, Any] = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
) -> UserListResponse:
    """列出所有用户（管理员）"""
    # 安全修复: 限制分页参数范围
    skip = max(0, skip)
    limit = max(1, min(limit, 100))

    users, total = await db.list_users(skip, limit)

    return UserListResponse(
        users=[
            UserResponse(
                id=u["id"],
                email=u["email"],
                full_name=u.get("full_name"),
                role=u["role"],
                is_active=u["is_active"],
                created_at=u.get("created_at"),
            )
            for u in users
        ],
        total=total,
    )


@router.put("/users/{user_id}/role")
async def change_user_role(
    user_id: str,
    role: str,
    admin: dict[str, Any] = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
) -> dict[str, str]:
    """修改用户角色（管理员）"""
    if role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="无效的角色，必须为 user 或 admin")

    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    await db.set_user_role(user_id, role)
    await db.log_activity(
        admin["id"], "change_role", "user", user_id, {"new_role": role}
    )

    return {"message": f"用户角色已更新为 {role}"}


@router.put("/users/{user_id}/active")
async def toggle_user_active(
    user_id: str,
    is_active: bool,
    admin: dict[str, Any] = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
) -> dict[str, str]:
    """激活/停用用户（管理员）"""
    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    await db.set_user_active(user_id, is_active)
    await db.log_activity(
        admin["id"], "toggle_active", "user", user_id, {"is_active": is_active}
    )

    # 如果停用用户，撤销其所有 Token
    if not is_active:
        await db.revoke_all_user_tokens(user_id)

    status = "激活" if is_active else "停用"
    return {"message": f"用户已{status}"}


@router.get("/stats", response_model=SystemStatsResponse)
async def system_stats(
    admin: dict[str, Any] = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
) -> SystemStatsResponse:
    """获取系统统计信息（管理员）"""
    stats = await db.get_system_stats()

    return SystemStatsResponse(
        total_users=stats["total_users"],
        total_projects=stats["total_projects"],
        total_papers=stats["total_papers"],
        active_users=stats["active_users"],
    )
