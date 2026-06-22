"""
认证服务

提供密码哈希和 JWT Token 管理功能。
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import structlog
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..config import get_settings

logger = structlog.get_logger()


class PasswordService:
    """密码哈希服务 (Argon2id)"""

    def __init__(self) -> None:
        self._hasher = PasswordHasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
        )

    def hash_password(self, plain: str) -> str:
        """哈希密码"""
        return self._hasher.hash(plain)

    def verify_password(self, plain: str, hashed: str) -> bool:
        """验证密码"""
        try:
            return self._hasher.verify(hashed, plain)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    def needs_rehash(self, hashed: str) -> bool:
        """检查是否需要重新哈希"""
        return self._hasher.check_needs_rehash(hashed)


class TokenService:
    """JWT Token 服务"""

    def __init__(self) -> None:
        settings = get_settings()
        self.secret_key = settings.jwt_secret_key
        self.algorithm = settings.jwt_algorithm
        self.access_token_expire = timedelta(
            minutes=settings.access_token_expire_minutes
        )
        self.refresh_token_expire = timedelta(days=settings.refresh_token_expire_days)

    def create_access_token(self, user_id: str, role: str) -> str:
        """创建 Access Token"""
        now = datetime.now(UTC)
        payload = {
            "sub": user_id,
            "role": role,
            "type": "access",
            "exp": now + self.access_token_expire,
            "iat": now,
            "jti": str(uuid.uuid4()),
        }
        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(self, user_id: str) -> tuple[str, str]:
        """创建 Refresh Token，返回 (raw_token, token_hash)"""
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        return raw_token, token_hash

    def decode_access_token(self, token: str) -> dict[str, Any]:
        """解码 Access Token"""
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            if payload.get("type") != "access":
                raise jwt.InvalidTokenError("Invalid token type")
            return payload
        except jwt.ExpiredSignatureError:
            raise ValueError("Token has expired") from None
        except jwt.InvalidTokenError as e:
            raise ValueError(f"Invalid token: {e}") from e

    def hash_refresh_token(self, raw_token: str) -> str:
        """哈希 Refresh Token"""
        return hashlib.sha256(raw_token.encode()).hexdigest()


# 模块级单例
_password_service: PasswordService | None = None
_token_service: TokenService | None = None


def get_password_service() -> PasswordService:
    """获取密码服务单例"""
    global _password_service
    if _password_service is None:
        _password_service = PasswordService()
    return _password_service


def get_token_service() -> TokenService:
    """获取 Token 服务单例"""
    global _token_service
    if _token_service is None:
        _token_service = TokenService()
    return _token_service
