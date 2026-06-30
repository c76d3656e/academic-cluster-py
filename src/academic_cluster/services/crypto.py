"""
Fernet 加密服务

用于加密/解密 Provider API Key（AES-128-CBC + HMAC-SHA256）。
密钥通过 PROVIDER_ENCRYPTION_KEY 环境变量管理，未设置时自动生成并持久化。
"""

import base64
import hashlib
from pathlib import Path

import structlog
from cryptography.fernet import Fernet, InvalidToken

logger = structlog.get_logger()

_fernet: Fernet | None = None

_KEY_FILE = "/app/data/.provider_encryption_key"


def _load_or_generate_key() -> str:
    """从文件或环境变量获取密钥，未设置时自动生成并持久化。"""
    # 1. 环境变量优先
    from ..config import get_settings

    settings = get_settings()
    key = settings.provider_encryption_key
    if key:
        return key

    # 2. 尝试从持久化文件读取
    key_file = Path(_KEY_FILE)
    if key_file.exists():
        stored = key_file.read_text().strip()
        if stored:
            logger.info("Loaded provider encryption key from file")
            return stored

    # 3. 自动生成并保存
    key = Fernet.generate_key().decode()
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(key)
        logger.info("Auto-generated provider encryption key and persisted to file")
    except OSError as e:
        logger.warning(
            "Could not persist encryption key to file, using in-memory only",
            error=str(e),
        )

    return key


def _get_fernet() -> Fernet:
    """获取或初始化 Fernet 实例"""
    global _fernet
    if _fernet is not None:
        return _fernet

    key = _load_or_generate_key()

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
