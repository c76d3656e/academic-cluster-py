"""
管理后台 - 用户管理

提供用户列表、创建、删除、角色变更、激活状态切换、用量查询等端点。
"""

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ...models.user import UserListResponse, UserResponse
from ...services.auth import PasswordService, get_password_service
from ...services.database import DatabaseService, get_database
from ..dependencies import require_admin

logger = structlog.get_logger()

router = APIRouter(tags=["admin-users"])


# =============================================================================
# 请求模型
# =============================================================================


class AdminCreateUserRequest(BaseModel):
    """管理员创建用户请求"""

    email: str = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: str | None = Field(None, max_length=255)
    role: str = Field("user", pattern="^(user|admin)$")


class ChangeRoleRequest(BaseModel):
    """修改角色请求"""

    role: str = Field(..., pattern="^(user|admin)$")


class ToggleActiveRequest(BaseModel):
    """切换激活状态请求"""

    is_active: bool


# =============================================================================
# 响应模型
# =============================================================================


class UserUsageResponse(BaseModel):
    """用户用量响应"""

    user_id: str
    total_projects: int
    total_activities: int


# =============================================================================
# 端点
# =============================================================================


@router.get("", response_model=UserListResponse)
async def list_users(
    skip: int = 0,
    limit: int = 20,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """列出所有用户"""
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


@router.post("", response_model=UserResponse)
async def create_user(
    body: AdminCreateUserRequest,
    request: Request,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
    password_service: PasswordService = Depends(get_password_service),
):
    """管理员创建用户"""
    existing = await db.get_user_by_email(body.email)
    if existing:
        raise HTTPException(status_code=400, detail="该邮箱已被注册")

    hashed_password = password_service.hash_password(body.password)

    user_id = await db.save_user(
        {
            "email": body.email,
            "hashed_password": hashed_password,
            "full_name": body.full_name,
            "role": body.role,
            "is_active": True,
        }
    )

    await db.log_activity(
        admin["id"],
        "admin_create_user",
        "user",
        user_id,
        {"email": body.email, "role": body.role},
        ip_address=request.client.host if request.client else None,
    )

    user = await db.get_user_by_id(user_id)
    logger.info("Admin created user", admin_id=admin["id"], user_id=user_id)

    return UserResponse(
        id=user["id"],
        email=user["email"],
        full_name=user.get("full_name"),
        role=user["role"],
        is_active=user["is_active"],
        created_at=user.get("created_at"),
    )


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    request: Request,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """删除用户"""
    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 防止管理员删除自己
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="不能删除自己的账户")

    # 撤销所有 Token
    await db.revoke_all_user_tokens(user_id)

    # 删除用户（使用原始 SQL，因为 DatabaseService 没有 delete_user 方法）
    from sqlalchemy import text

    async with db.session() as session:
        await session.execute(
            text("DELETE FROM users WHERE id = :id"),
            {"id": user_id},
        )

    await db.log_activity(
        admin["id"],
        "admin_delete_user",
        "user",
        user_id,
        {"email": user["email"]},
        ip_address=request.client.host if request.client else None,
    )

    logger.info("Admin deleted user", admin_id=admin["id"], user_id=user_id)
    return {"message": "用户已删除"}


@router.patch("/{user_id}/role")
async def change_user_role(
    user_id: str,
    body: ChangeRoleRequest,
    request: Request,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """修改用户角色"""
    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    await db.set_user_role(user_id, body.role)

    await db.log_activity(
        admin["id"],
        "admin_change_role",
        "user",
        user_id,
        {"old_role": user["role"], "new_role": body.role},
        ip_address=request.client.host if request.client else None,
    )

    logger.info(
        "Admin changed user role",
        admin_id=admin["id"],
        user_id=user_id,
        new_role=body.role,
    )
    return {"message": f"用户角色已更新为 {body.role}"}


@router.patch("/{user_id}/active")
async def toggle_user_active(
    user_id: str,
    body: ToggleActiveRequest,
    request: Request,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """切换用户激活状态"""
    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 防止管理员停用自己
    if user_id == admin["id"] and not body.is_active:
        raise HTTPException(status_code=400, detail="不能停用自己的账户")

    await db.set_user_active(user_id, body.is_active)

    # 如果停用用户，撤销其所有 Token
    if not body.is_active:
        await db.revoke_all_user_tokens(user_id)

    await db.log_activity(
        admin["id"],
        "admin_toggle_active",
        "user",
        user_id,
        {"is_active": body.is_active},
        ip_address=request.client.host if request.client else None,
    )

    status = "激活" if body.is_active else "停用"
    logger.info(
        "Admin toggled user active",
        admin_id=admin["id"],
        user_id=user_id,
        is_active=body.is_active,
    )
    return {"message": f"用户已{status}"}


@router.get("/{user_id}/usage", response_model=UserUsageResponse)
async def get_user_usage(
    user_id: str,
    admin: dict = Depends(require_admin),
    db: DatabaseService = Depends(get_database),
):
    """获取用户用量详情"""
    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 查询用户的项目数和活动数
    from sqlalchemy import text

    async with db.session() as session:
        projects_result = await session.execute(
            text("SELECT COUNT(*) FROM projects WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        total_projects = projects_result.scalar()

        activities_result = await session.execute(
            text("SELECT COUNT(*) FROM user_activities WHERE user_id = :user_id"),
            {"user_id": user_id},
        )
        total_activities = activities_result.scalar()

    return UserUsageResponse(
        user_id=user_id,
        total_projects=total_projects,
        total_activities=total_activities,
    )
