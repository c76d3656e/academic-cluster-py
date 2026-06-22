"""
Console 个人资料路由

提供用户个人资料查询和修改端点。
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ...services.auth import PasswordService, get_password_service
from ...services.database import DatabaseService, get_database
from ..dependencies import get_current_user

logger = structlog.get_logger()

router = APIRouter()


# =============================================================================
# 请求/响应模型
# =============================================================================


class ProfileResponse(BaseModel):
    """用户个人资料响应"""

    id: str
    email: str
    full_name: str | None = None
    role: str = "user"
    is_active: bool = True


class ProfileUpdateRequest(BaseModel):
    """更新个人资料请求"""

    full_name: str | None = Field(None, max_length=255)


class PasswordChangeRequest(BaseModel):
    """修改密码请求"""

    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=128)


# =============================================================================
# 端点
# =============================================================================


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    current_user: dict = Depends(get_current_user),
):
    """获取当前用户个人资料"""
    return ProfileResponse(
        id=current_user["id"],
        email=current_user["email"],
        full_name=current_user.get("full_name"),
        role=current_user["role"],
        is_active=current_user.get("is_active", True),
    )


@router.patch("/profile", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
):
    """更新当前用户个人资料（仅 full_name）"""
    if body.full_name is not None:
        await db.update_user(current_user["id"], {"full_name": body.full_name})

    user = await db.get_user_by_id(current_user["id"])
    return ProfileResponse(
        id=user["id"],
        email=user["email"],
        full_name=user.get("full_name"),
        role=user["role"],
        is_active=user.get("is_active", True),
    )


@router.post("/profile/password")
async def change_password(
    body: PasswordChangeRequest,
    current_user: dict = Depends(get_current_user),
    db: DatabaseService = Depends(get_database),
    password_service: PasswordService = Depends(get_password_service),
):
    """修改密码"""
    # 验证当前密码
    if not password_service.verify_password(
        body.current_password, current_user["hashed_password"]
    ):
        raise HTTPException(status_code=400, detail="当前密码错误")

    # 哈希新密码并更新
    new_hashed = password_service.hash_password(body.new_password)
    await db.update_user(current_user["id"], {"hashed_password": new_hashed})

    logger.info("User changed password", user_id=current_user["id"])

    return {"message": "密码修改成功"}
