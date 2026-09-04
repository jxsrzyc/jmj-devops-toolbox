"""身份认证 + 权限管理工具 (SHA-256 本地认证 + LDAP + RBAC 角色权限)

v2.15 权限体系升级：
- 权限点两级化：模块级（侧边栏一级菜单）+ 子标签级（二级菜单，如 IP 查询 / 生成器）
- RBAC：用户挂角色（roles 表），有效权限 = 所有角色权限并集（每次请求实时计算，改角色即时生效）
- 继承规则：勾选子权限自动获得父模块权限；拥有模块级权限自动解锁全部子权限
- 兼容：role_ids 为空的用户回退使用旧 permissions 字段（存量数据 / LDAP JIT 无感过渡）
"""

import hashlib
import json
import os
import logging
from functools import wraps
from flask import session, redirect, url_for, jsonify, render_template, g

logger = logging.getLogger(__name__)

# ==================== 权限点定义（两级） ====================

# 模块级权限 — 控制侧边栏一级菜单
MODULE_PERMISSIONS = {
    "release": "发版管理",
    "credentials": "服务凭证管理",
    "domains": "域名管理",
    "nettools": "网络工具",
    "utils": "运维小工具",
    "bizlinks": "业务跳转",
}

# 子标签级权限（v2.15）— key 规则：模块缩写:子标签
SUB_PERMISSIONS = {
    # 发版管理
    "rel:params": "蓝鲸发版参数管理",
    "rel:ciorders": "云效创建变更单参数",
    "rel:cidevflow": "云效运行研发流程参数",
    "rel:fixrecords": "发版修复记录",
    # 服务凭证管理（按环境）
    "cred:all": "凭证·业务环境汇总",
    "cred:超融合电信开发环境": "凭证·超融合电信开发环境",
    "cred:超融合南沙生产环境": "凭证·超融合南沙生产环境",
    "cred:私有云测试环境": "凭证·私有云测试环境",
    "cred:私有云生产环境": "凭证·私有云生产环境",
    "cred:预生产环境": "凭证·预生产环境",
    "cred:国内生产环境": "凭证·国内生产环境",
    "cred:新加坡生产环境": "凭证·新加坡生产环境",
    "cred:北美生产环境": "凭证·北美生产环境",
    # 域名管理（按主域名）
    "dom:jmj1995.com": "域名·jmj1995.com",
    "dom:jiumaojiu.com": "域名·jiumaojiu.com",
    "dom:datousoft.com": "域名·datousoft.com",
    # 网络工具
    "net:ping": "PING 检测",
    "net:tcping": "TCPing",
    "net:route": "路由查询",
    "net:mtr": "MTR 路由",
    "net:dns": "DNS 查询",
    "net:whois": "Whois 查询",
    "net:ssl": "SSL 检测",
    "net:ip": "IP 查询",
    "net:cdn": "CDN 查询",
    # 运维小工具
    "ut:json": "JSON 格式化",
    "ut:encode": "编码解码·哈希",
    "ut:yaml": "K8s YAML 检测",
    "ut:health": "HTTP 健康检查",
    "ut:curl": "Curl 请求调试",
    "ut:webhook": "Webhook 调试",
    "ut:cert": "证书批量到期检测",
    "ut:batch": "批量端口连通性检测",
    "ut:pingping": "批量PING检测",
    "ut:diff": "文本比较",
    "ut:dedup": "文本去重",
    "ut:generator": "生成器",
    "ut:cidr": "CIDR 子网计算器",
    "ut:timestamp": "时间戳换算",
    "ut:scicalc": "科学计算器",
}

# 子权限 → 父模块映射
SUB_TO_MODULE = {
    "rel:params": "release", "rel:ciorders": "release", "rel:cidevflow": "release", "rel:fixrecords": "release",
    **{k: "credentials" for k in SUB_PERMISSIONS if k.startswith("cred:")},
    **{k: "domains" for k in SUB_PERMISSIONS if k.startswith("dom:")},
    **{k: "nettools" for k in SUB_PERMISSIONS if k.startswith("net:")},
    **{k: "utils" for k in SUB_PERMISSIONS if k.startswith("ut:")},
}

# 全部权限点（模块级 + 子标签级）
ALL_PERMISSIONS = list(MODULE_PERMISSIONS.keys()) + list(SUB_PERMISSIONS.keys())

# 凭证环境 / 域名主域（与侧边栏一致）
CRED_ENVS = [
    "超融合电信开发环境", "超融合南沙生产环境", "私有云测试环境", "私有云生产环境",
    "预生产环境", "国内生产环境", "新加坡生产环境", "北美生产环境",
]
DOMAIN_ROOTS = ["jmj1995.com", "jiumaojiu.com", "datousoft.com"]

# 前端权限树（角色编辑弹窗用）
PERM_TREE = []
for _mk, _mv in MODULE_PERMISSIONS.items():
    _children = []
    for _sk, _sv in SUB_PERMISSIONS.items():
        if SUB_TO_MODULE[_sk] != _mk:
            continue
        # 凭证/域名子项展示去掉「凭证·」「域名·」前缀，模块名下更清爽
        _children.append({"key": _sk, "label": _sv.split("·", 1)[-1] if _sk.startswith(("cred:", "dom:")) else _sv})
    PERM_TREE.append({"key": _mk, "label": _mv, "children": _children})

# 内置种子角色（database.py 建表后 seed 用；permissions 存逗号分隔权限点或 *）
_NET_ALL = ",".join(f"net:{t}" for t in ["ping", "tcping", "route", "mtr", "dns", "whois", "ssl", "ip", "cdn"])
_UT_ALL = ",".join(f"ut:{t}" for t in ["json", "encode", "yaml", "health", "curl", "webhook", "cert",
                                        "batch", "pingping", "diff", "dedup", "generator", "cidr", "timestamp", "scicalc"])
_REL_ALL = ",".join(["rel:params", "rel:ciorders", "rel:cidevflow", "rel:fixrecords"])
SYSTEM_ROLES = [
    {"name": "管理员", "description": "超级管理员，拥有全部权限", "permissions": "*"},
    {"name": "发版", "description": "仅发版管理-蓝鲸发版参数管理", "permissions": "rel:params"},
    {"name": "运维", "description": "网络工具 + 运维小工具 + 业务跳转", "permissions": f"{_NET_ALL},{_UT_ALL},bizlinks"},
    {"name": "开发", "description": "发版管理 + 运维小工具", "permissions": f"{_REL_ALL},{_UT_ALL}"},
    {"name": "测试", "description": "发版管理 + 网络工具", "permissions": f"{_REL_ALL},{_NET_ALL}"},
]


def hash_password(password: str) -> str:
    """SHA-256 加盐哈希"""
    salt = os.environ.get("PWD_SALT", "lanqi-svc-params-2026")
    return hashlib.sha256((salt + password).encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


# ==================== 有效权限计算（RBAC） ====================

def _parse_perms(s: str):
    """逗号分隔权限串 → 列表"""
    return [p.strip() for p in (s or "").split(",") if p.strip()]


def expand_perms(perms) -> set:
    """权限继承展开（单向：模块 → 子权限）：
    - * 通配 → 全部
    - 拥有模块级权限 → 解锁该模块全部子权限
    - 仅拥有子权限时不反向解锁兄弟子权限（保证细粒度控制不被放大）
    """
    perms = set(perms or [])
    if "*" in perms:
        return {"*"}
    out = {p for p in perms if p}
    for sub, parent in SUB_TO_MODULE.items():
        if parent in out:
            out.add(sub)
    return out


def get_effective_perms() -> set:
    """当前请求的有效权限集（每次请求实时从 DB 计算并缓存到 flask.g，
    修改角色/用户权限后即时生效，无需重新登录）"""
    if "user_id" not in session:
        return set()
    if session.get("permissions") == "*":
        return {"*"}
    if hasattr(g, "_effective_perms"):
        return g._effective_perms
    perms = set()
    try:
        from database import db
        user = db.get_user_by_username(session.get("username", ""))
        if user is not None:
            user = dict(user)
            role_ids = _parse_perms(user.get("role_ids", ""))
            if role_ids:
                for role in db.get_roles_by_ids(role_ids):
                    perms.update(_parse_perms(role["permissions"]))
            else:
                # 兼容：未挂角色的用户回退旧 permissions 字段（存量数据 / LDAP JIT）
                perms.update(_parse_perms(user.get("permissions", "")))
    except Exception as e:
        logger.warning("计算有效权限失败，回退 session 权限: %s", e)
        perms.update(_parse_perms(session.get("permissions", "")))
    g._effective_perms = expand_perms(perms)
    return g._effective_perms


def _roles_display() -> str:
    """用户面板展示用：角色名（无角色时回退权限串 / 管理员标识）"""
    if session.get("permissions") == "*":
        return "管理员"
    try:
        from database import db
        user = db.get_user_by_username(session.get("username", ""))
        if user is not None:
            user = dict(user)
            role_ids = _parse_perms(user.get("role_ids", ""))
            if role_ids:
                names = [r["name"] for r in db.get_roles_by_ids(role_ids)]
                if names:
                    return "、".join(names)
            if (user.get("permissions") or "").strip():
                return user["permissions"]
    except Exception as e:
        logger.warning("解析用户角色失败: %s", e)
    return session.get("permissions", "")


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
    """要求特定权限（API 用）。支持模块级（nettools）与子标签级（net:ip）权限点。
    - 子权限点：严格匹配有效权限集
    - 模块级权限点：拥有模块本身或该模块任一子权限即放行（具体数据路由内部再做细粒度校验）
    - perm_key="admin"：仅 * 通配（管理员）可通过"""
    def decorator(f):
        @wraps(f)
        def decorated(*a, **kw):
            if "user_id" not in session:
                return jsonify({"code": 401, "message": "请先登录"}), 401
            if user_has_perm(perm_key):
                return f(*a, **kw)
            return jsonify({"code": 403, "message": "无此权限"}), 403
        return decorated
    return decorator


def user_has_perm(perm_key: str) -> bool:
    """当前用户是否有某权限（模板 + 动态资源校验用）。
    模块级权限点特殊：拥有该模块任一子权限即视为"可见"（侧边栏分组显示），
    但实际 API 校验走的是具体子权限点（require_perm 严格匹配）。"""
    if "user_id" not in session:
        return False
    eff = get_effective_perms()
    if "*" in eff or perm_key in eff:
        return True
    if perm_key in MODULE_PERMISSIONS:
        return any(sk in eff for sk, parent in SUB_TO_MODULE.items() if parent == perm_key)
    return False


def get_user_context():
    """返回模板可用的用户上下文"""
    perm_map = {k: user_has_perm(k) for k in ALL_PERMISSIONS}
    perm_map["admin"] = session.get("permissions") == "*"
    return {
        "logged_in": "user_id" in session,
        "username": session.get("username", ""),
        "display_name": session.get("display_name", ""),
        "permissions": session.get("permissions", ""),
        "roles_display": _roles_display(),
        "perm_json": json.dumps(perm_map, ensure_ascii=False),
        "perm_tree_json": json.dumps(PERM_TREE, ensure_ascii=False),
        "has_perm": user_has_perm,
    }
