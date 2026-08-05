"""身份认证 + 权限管理工具 (SHA-256 零依赖)"""

import hashlib
import os
from functools import wraps
from flask import session, redirect, url_for, jsonify, render_template

# 权限点定义 — 所有侧边栏可控制项
PERMISSIONS = {
    "release": "发版管理",
    "credentials": "服务凭证管理",
    "domains": "域名管理",
}

ALL_PERMISSIONS = list(PERMISSIONS.keys())


def hash_password(password: str) -> str:
    """SHA-256 加盐哈希"""
    salt = os.environ.get("PWD_SALT", "lanqi-svc-params-2026")
    return hashlib.sha256((salt + password).encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


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
