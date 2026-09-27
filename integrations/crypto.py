"""集成密钥字段的静态加密（cryptography.Fernet）。

- 密钥来自 settings.FIELD_ENCRYPTION_KEY（放 .env，不提交、不写死、不入库）。
- 明文只在运行时按需解密（build_sdk / 钉钉取 token 时），不在模型加载或后台展示时解密。
- 密钥丢失 = 已存密文不可恢复，需重新在后台录入。
"""

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class SecretCryptoError(RuntimeError):
    pass


def _fernet():
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "") or ""
    if not key:
        raise ImproperlyConfigured(
            "未配置 FIELD_ENCRYPTION_KEY，无法加/解密集成密钥字段。请在 .env 里设置（见 .env.example）。"
        )
    from cryptography.fernet import Fernet

    try:
        return Fernet(key.encode("ascii") if isinstance(key, str) else key)
    except Exception as exc:  # 密钥格式非法
        raise ImproperlyConfigured(f"FIELD_ENCRYPTION_KEY 不是合法的 Fernet 密钥：{exc}") from exc


def encrypt(plaintext):
    """明文 → 密文(str)。空值原样返回空串。"""
    if not plaintext:
        return ""
    return _fernet().encrypt(str(plaintext).encode("utf-8")).decode("ascii")


def decrypt(token):
    """密文 → 明文(str)。空值返回空串；密文与当前密钥不匹配时抛错，不静默回退。"""
    if not token:
        return ""
    from cryptography.fernet import InvalidToken

    try:
        return _fernet().decrypt(str(token).encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretCryptoError("集成密钥解密失败：密文与当前 FIELD_ENCRYPTION_KEY 不匹配。") from exc


def is_encrypted(value):
    """是否已是本系统密文（存量迁移的幂等判据）。空值视为无需处理。"""
    if not value:
        return True
    try:
        decrypt(value)
        return True
    except Exception:
        return False
