"""密码加密工具 - AES 对称加密（Fernet: AES-128-CBC + HMAC-SHA256）

安全说明：
- 密钥来自环境变量 CRED_SECRET_KEY，未设置时使用内置默认值派生
- 生产环境务必设置 CRED_SECRET_KEY（32 字节 base64 编码的 Fernet key）
- 加密后的密文格式: gAAAAAB...（Fernet 标准格式）
- 本模块不打印、不记录任何明文
"""

import os
import base64
import hashlib

DEFAULT_SECRET = "lanqi-svc-params-credential-secret-2026"


def _get_key() -> str:
    """获取 Fernet 密钥（返回 urlsafe base64 字符串，Fernet 期望的格式）：
    优先环境变量 CRED_SECRET_KEY（44 字符 urlsafe base64），否则从默认值派生
    """
    env_key = os.environ.get("CRED_SECRET_KEY", "").strip()
    if env_key:
        try:
            # 校验是否为有效 Fernet key（32 字节 urlsafe base64）
            decoded = base64.urlsafe_b64decode(env_key.encode())
            if len(decoded) == 32:
                return env_key
        except Exception:
            pass
    # 派生：默认值 sha256 → 32 字节 → urlsafe base64 字符串
    digest = hashlib.sha256(DEFAULT_SECRET.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode()


def _fernet():
    from cryptography.fernet import Fernet
    return Fernet(_get_key())


def encrypt_password(plaintext):
    """加密明文密码，返回 Fernet 密文字符串。空值/None 直接返回原值。"""
    if plaintext is None:
        return ""
    plaintext = str(plaintext)
    if plaintext == "":
        return ""
    try:
        return _fernet().encrypt(plaintext.encode()).decode()
    except Exception:
        return ""


def decrypt_password(ciphertext):
    """解密密码密文，返回明文。非 Fernet 格式（旧数据明文）原样返回。"""
    if not ciphertext:
        return ""
    ciphertext = str(ciphertext)
    if not ciphertext.startswith("gAAAA"):
        # 旧数据可能是明文（未加密的存量数据），原样返回
        return ciphertext
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except Exception:
        return ""


def mask_password(plaintext):
    """脱敏显示：有值显示 ●●●●●●●●，空显示 '-'"""
    if not plaintext:
        return "-"
    return "●●●●●●●●"
