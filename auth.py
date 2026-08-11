"""身份认证 + 权限管理工具 (SHA-256 本地认证 + LDAP)"""

import hashlib
import os
import logging
from functools import wraps
from flask import session, redirect, url_for, jsonify, render_template

logger = logging.getLogger(__name__)

# 权限点定义 — 所有侧边栏可控制项
PERMISSIONS = {
    "release": "发版管理",
    "credentials": "服务凭证管理",
    "domains": "域名管理",
    "nettools": "网络工具",
    "utils": "运维小工具",
}

ALL_PERMISSIONS = list(PERMISSIONS.keys())


def hash_password(password: str) -> str:
    """SHA-256 加盐哈希"""
    salt = os.environ.get("PWD_SALT", "lanqi-svc-params-2026")
    return hashlib.sha256((salt + password).encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


# ==================== LDAP 认证 ====================

def ldap_authenticate(username: str, password: str):
    """LDAP 认证：先 Bind 服务账号搜索用户 DN，再用用户 DN + 密码 Bind 验证。
    成功返回用户信息 dict，失败返回 None。

    AuthFilter 支持 %s 占位（openldap: (&(uid=%s)) / AD: (&(sAMAccountName=%s))）
    """
    if os.environ.get("LDAP_ENABLE", "").lower() not in ("1", "true", "yes", "on"):
        return None
    if not username or not password:
        return None
    try:
        import ldap3
        from ldap3 import Server, Connection, Tls, ALL
        import ssl

        host = os.environ.get("LDAP_HOST", "")
        port = int(os.environ.get("LDAP_PORT", "389"))
        base_dn = os.environ.get("LDAP_BASE_DN", "")
        bind_user = os.environ.get("LDAP_BIND_USER", "")
        bind_pass = os.environ.get("LDAP_BIND_PASS", "")
        auth_filter = os.environ.get("LDAP_AUTH_FILTER", "(&(objectClass=inetOrgPerson)(uid=%s))")
        use_tls = os.environ.get("LDAP_TLS", "").lower() in ("1", "true", "yes", "on")
        use_starttls = os.environ.get("LDAP_STARTTLS", "").lower() in ("1", "true", "yes", "on")

        # TLS 配置（内网 LDAP 可能自签名证书，不校验证书）
        tls = Tls(validate=ssl.CERT_NONE) if (use_tls or use_starttls) else None
        server = Server(host, port=port, use_ssl=use_tls, tls=tls, get_info=ALL)

        # 1. Bind 服务账号（读用户 DN）
        conn = Connection(server, user=bind_user, password=bind_pass, auto_bind=True,
                          raise_exceptions=True)
        if use_starttls and not use_tls:
            try:
                conn.start_tls()
            except Exception:
                logger.warning("LDAP start_tls 失败，继续尝试明文")
        # 2. 搜索目标用户
        search_filter = auth_filter % username
        if not conn.search(base_dn, search_filter, attributes=["uid", "displayName", "mail", "telephoneNumber", "cn", "name"]):
            conn.unbind()
            return None
        if not conn.entries:
            conn.unbind()
            return None
        entry = conn.entries[0]
        user_dn = entry.entry_dn
        conn.unbind()

        # 3. 用用户 DN + 密码认证
        conn2 = Connection(server, user=user_dn, password=password, auto_bind=True,
                           raise_exceptions=True)
        conn2.unbind()

        # 提取用户属性（ldap3 属性取值）
        def attr(*names, default=""):
            for n in names:
                if n in entry:
                    v = entry[n].value
                    if v:
                        return str(v)
            return default

        return {
            "username": attr("uid", "sAMAccountName", default=username),
            "display_name": attr("displayName", "name", "cn", default=username),
            "email": attr("mail"),
            "phone": attr("telephoneNumber"),
        }
    except Exception as e:
        logger.warning("LDAP 认证异常: %s", e)
        return None


def login_required(f=None, *, api=False):
    """要求登录的装饰器
    Usage:
        @login_required              # HTML 页面 → 302 重定向到 /login
        @login_required(api=True)    # API → 返回 401 JSON
    """
    if f is not None and callable(f):
        # 不带参数调用: @login_required
        @wraps(f)
        def decorated(*a, **kw):
            if "user_id" not in session:
                return redirect(url_for("login_page"))
            return f(*a, **kw)
        return decorated

    # 带参数调用: @login_required(api=True)
    def decorator(fn):
        @wraps(fn)
        def decorated(*a, **kw):
            if api:
                if "user_id" not in session:
                    return jsonify({"code": 401, "message": "请先登录"}), 401
            else:
                if "user_id" not in session:
                    return redirect(url_for("login_page"))
            return fn(*a, **kw)
        return decorated
    return decorator


def require_perm(perm_key: str):
    """要求特定权限（API 用）"""
    def decorator(f):
        @wraps(f)
        def decorated(*a, **kw):
            if "user_id" not in session:
                return jsonify({"code": 401, "message": "请先登录"}), 401
            perms = session.get("permissions", "")
            if perms == "*" or perm_key in perms.split(","):
                return f(*a, **kw)
            return jsonify({"code": 403, "message": "无此权限"}), 403
        return decorated
    return decorator


def user_has_perm(perm_key: str) -> bool:
    """当前用户是否有某权限（模板用）"""
    if "user_id" not in session:
        return False
    perms = session.get("permissions", "")
    return perms == "*" or perm_key in perms.split(",")


def get_user_context():
    """返回模板可用的用户上下文"""
    return {
        "logged_in": "user_id" in session,
        "username": session.get("username", ""),
        "display_name": session.get("display_name", ""),
        "permissions": session.get("permissions", ""),
        "has_perm": user_has_perm,
    }
