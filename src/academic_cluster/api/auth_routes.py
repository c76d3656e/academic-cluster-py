"""
认证 API 路由

提供用户注册、登录、Token 刷新、用户管理等端点。
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..config import get_settings
from ..models.user import (
    RefreshTokenRequest,
    TokenResponse,
    UserCreate,
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
from .dependencies import get_current_user

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["auth"])

# =============================================================================
# 公开端点
# =============================================================================


def _set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path="/api/auth",
        secure=settings.is_production,
        httponly=True,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path="/api/auth",
        secure=settings.is_production,
        httponly=True,
        samesite="strict",
    )


def _refresh_token_from_request(
    request: Request, body: RefreshTokenRequest | None
) -> str:
    settings = get_settings()
    cookie_token = request.cookies.get(settings.refresh_cookie_name)
    if cookie_token:
        return cookie_token
    if (
        body is not None
        and settings.auth_allow_legacy_refresh_body
        and not settings.is_production
    ):
        return body.refresh_token
    raise HTTPException(status_code=401, detail="Refresh session is missing")


@router.post("/register", response_model=UserResponse)
async def register(
    body: UserCreate,
    request: Request,
    db: DatabaseService = Depends(get_database),
    password_service: PasswordService = Depends(get_password_service),
) -> UserResponse:
    """用户注册"""
    if not get_settings().registration_enabled:
        raise HTTPException(status_code=403, detail="Public registration is disabled")
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
        user_id,
        "register",
        ip_address=getattr(request.state, "client_ip", None),
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
    response: Response,
    db: DatabaseService = Depends(get_database),
    password_service: PasswordService = Depends(get_password_service),
    token_service: TokenService = Depends(get_token_service),
) -> TokenResponse:
    """用户登录"""
    user = await db.get_user_by_email(body.email)
    if not user:
        password_service.burn_unknown_user_check(body.password)
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
    access_token = token_service.create_access_token(
        user["id"], user["role"], int(user.get("token_version") or 0)
    )
    raw_refresh_token, token_hash = token_service.create_refresh_token(user["id"])

    # 存储 Refresh Token
    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    await db.save_refresh_token(token_hash, user["id"], expires_at)

    # 更新最后登录时间
    await db.update_user(user["id"], {"last_login_at": datetime.now(UTC)})

    await db.log_activity(
        user["id"],
        "login",
        ip_address=getattr(request.state, "client_ip", None),
    )

    logger.info("User logged in", user_id=user["id"], email=body.email)

    _set_refresh_cookie(response, raw_refresh_token)

    return TokenResponse(access_token=access_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: Request,
    response: Response,
    body: RefreshTokenRequest | None = None,
    db: DatabaseService = Depends(get_database),
    token_service: TokenService = Depends(get_token_service),
) -> TokenResponse:
    """刷新 Access Token"""
    raw_token = _refresh_token_from_request(request, body)
    token_hash = token_service.hash_refresh_token(raw_token)

    stored_token = await db.consume_refresh_token(token_hash)
    if not stored_token:
        raise HTTPException(status_code=401, detail="无效或已过期的 Refresh Token")

    # 获取用户信息
    user = await db.get_user_by_id(stored_token["user_id"])
    if not user or not user.get("is_active", False):
        raise HTTPException(status_code=401, detail="用户不存在或已被停用")

    # 创建新 Token
    access_token = token_service.create_access_token(
        user["id"], user["role"], int(user.get("token_version") or 0)
    )
    new_raw_token, new_token_hash = token_service.create_refresh_token(user["id"])

    settings = get_settings()
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    await db.save_refresh_token(new_token_hash, user["id"], expires_at)

    _set_refresh_cookie(response, new_raw_token)

    return TokenResponse(access_token=access_token)


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
) -> UserResponse:
    """更新当前用户非敏感资料；密码只能通过重新认证的专用端点修改。"""
    update_data = {}

    if body.full_name is not None:
        update_data["full_name"] = body.full_name

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
    request: Request,
    response: Response,
    body: RefreshTokenRequest | None = None,
    current_user: dict[str, Any] = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
    token_service: TokenService = Depends(get_token_service),
) -> dict[str, str]:
    """用户登出"""
    try:
        raw_token = _refresh_token_from_request(request, body)
    except HTTPException:
        raw_token = None
    if raw_token:
        token_hash = token_service.hash_refresh_token(raw_token)
        await db.revoke_refresh_token(token_hash)
    _clear_refresh_cookie(response)
    await db.log_activity(current_user["id"], "logout")

    return {"message": "登出成功"}
