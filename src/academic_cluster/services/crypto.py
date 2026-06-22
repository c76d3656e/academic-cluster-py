"""
Fernet 加密服务

用于加密/解密 Provider API Key（AES-128-CBC + HMAC-SHA256）。
密钥通过 PROVIDER_ENCRYPTION_KEY 环境变量管理。
"""

import base64
import hashlib

import structlog
from cryptography.fernet import Fernet, InvalidToken

logger = structlog.get_logger()

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """获取或初始化 Fernet 实例"""
    global _fernet
    if _fernet is not None:
        return _fernet

    from ..config import get_settings
    settings = get_settings()
    key = settings.provider_encryption_key

    if not key:
        # 自动生成一个临时 key（仅用于开发环境）
        key = Fernet.generate_key().decode()
        logger.warning(
            "No PROVIDER_ENCRYPTION_KEY set, using auto-generated key (NOT for production)"
        )

    # 如果是明文密码而非 Fernet key，派生一个合法的 Fernet key
    if not _is_fernet_key(key):
        key = _derive_fernet_key(key)

    _fernet = Fernet(key if isinstance(key, bytes) else key.encode())
    return _fernet


def _is_fernet_key(key: str) -> bool:
    """检查是否是合法的 Fernet key（base64 编码的 32 字节）"""
    try:
        decoded = base64.urlsafe_b64decode(key)
        return len(decoded) == 32
    except Exception:
        return False


def _derive_fernet_key(password: str) -> str:
    """从密码派生一个合法的 Fernet key（SHA-256 → base64）"""
    digest = hashlib.sha256(password.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode()


def encrypt_key(plain: str) -> str:
    """加密 API Key，返回 base64 编码的密文"""
    f = _get_fernet()
    return f.encrypt(plain.encode()).decode()


def decrypt_key(encrypted: str) -> str:
    """解密 API Key，返回明文"""
    f = _get_fernet()
    try:
        return f.decrypt(encrypted.encode()).decode()
    except InvalidToken:
        logger.error("Failed to decrypt key: invalid token or wrong encryption key")
        raise ValueError("解密失败：密钥无效或加密密钥不匹配") from None


def mask_key(plain: str) -> str:
    """掩码 API Key，如 sk-abc...xyz"""
    if not plain or len(plain) < 8:
        return "****"
    return f"{plain[:4]}...{plain[-3:]}"
