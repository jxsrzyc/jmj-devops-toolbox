#!/usr/bin/env python3
"""蓝鲸云效服务发版参数管理 - Flask 后端"""

import os
import sys
from datetime import datetime
from flask import Flask, jsonify, request, render_template, session, redirect, url_for
from flask_cors import CORS
from database import db
from models import ServiceParam
from excel_utils import excel_response, format_dt
from auth import login_required, require_perm, hash_password, get_user_context, ALL_PERMISSIONS, PERMISSIONS
from holidays_data import get_builtin_holidays

app = Flask(__name__)
CORS(app, supports_credentials=True)
app.secret_key = "lanqi-svc-params-secret-2026"

# 防 HTML/API 响应被浏览器缓存（确保 JS / API 修改立即生效）
@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# 数据库路径（可通过环境变量覆盖，适配 Docker/K8s）
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))
EXCEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "Downloads", "蓝鲸云效服务发版参数列表.xlsx")


# ==================== 页面路由 ====================

@app.route("/")
@login_required
def index():
    """首页 — 已登录才能访问（关键优化：不预渲染本机 IP，避免 cip.cc / ip-api 阻塞首屏）"""
    ctx = get_user_context()
    # IP 由前端 JS 异步加载（XHR /api/nettools/myip），首屏立即返回
    ctx["egress_ip"] = None
    ctx["build_ts"] = __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return render_template("index.html", **ctx)


@app.route("/login", methods=["GET", "POST"])
def login_page():
    """登录页面 — 支持本地账号 + LDAP 账号双认证源"""
    if request.method == "POST":
        data = request.get_json()
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()
        if not username or not password:
            return jsonify({"code": 400, "message": "用户名和密码不能为空"}), 400

        from auth import verify_password, ldap_authenticate, hash_password
        import secrets

        user = db.get_user_by_username(username)
        auth_source = user["auth_source"] if user else None

        # 分支 1：本地账号 → 本地 SHA-256 校验
        if user and auth_source == "local":
            if not verify_password(password, user["password_hash"]):
                return jsonify({"code": 401, "message": "用户名或密码错误"}), 401

        # 分支 2：LDAP 账号（已存在本地记录）→ LDAP 校验
        elif user and auth_source == "ldap":
            ldap_info = ldap_authenticate(username, password)
            if not ldap_info:
                return jsonify({"code": 401, "message": "用户名或密码错误"}), 401
            # 同步显示名（首次或变更后）
            if ldap_info.get("display_name") and ldap_info["display_name"] != user["display_name"]:
                db.update_user(user["id"], display_name=ldap_info["display_name"])

        # 分支 3：本地无此账号 → 尝试 LDAP，成功则 JIT 自动开通
        elif not user:
            ldap_info = ldap_authenticate(username, password)
            if not ldap_info:
                return jsonify({"code": 401, "message": "用户名或密码错误"}), 401
            default_perms = os.environ.get("LDAP_DEFAULT_PERMS", "release")
            display_name = ldap_info.get("display_name") or username
            # 本地密码置为随机值（LDAP 用户不走本地密码登录）
            db.create_user(
                username, secrets.token_hex(16),
                display_name=display_name,
                permissions=default_perms,
                auth_source="ldap",
            )
            user = db.get_user_by_username(username)

        # 登录成功 → 写 session
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["display_name"] = user["display_name"] or user["username"]
        session["permissions"] = user["permissions"]
        session["auth_source"] = user.get("auth_source", "local")
        db.add_activity(user["username"], "login", "系统", "登录了系统")
        return jsonify({"code": 0, "message": "登录成功", "data": {"username": user["username"]}})
    # GET — 已登录直接跳首页
    if "user_id" in session:
        return redirect(url_for("index"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/api/me")
def api_me():
    if "user_id" not in session:
        return jsonify({"code": 401})
    return jsonify({
        "code": 0,
        "data": {
            "username": session.get("username"),
            "display_name": session.get("display_name"),
            "permissions": session.get("permissions"),
            "auth_source": session.get("auth_source", "local"),
        }
    })


# ==================== 业务模块 & 环境 ====================

@app.route("/api/modules", methods=["GET"])
def get_modules():
    """获取所有业务模块列表（去重）"""
    modules = db.get_all_modules()
    return jsonify({"code": 0, "data": modules})


@app.route("/api/envs", methods=["GET"])
def get_envs():
    """获取所有环境列表（去重）"""
    envs = db.get_envs()
    return jsonify({"code": 0, "data": envs})


# ==================== 服务参数 CRUD ====================

@app.route("/api/services", methods=["GET"])
def get_services():
    """获取服务列表，支持按业务模块、环境、关键词筛选"""
    module = request.args.get("module", "").strip()
    env = request.args.get("env", "").strip()
    keyword = request.args.get("keyword", "").strip()
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))

    services, total = db.get_services(module=module, keyword=keyword, env=env, page=page, page_size=page_size)
    return jsonify({
        "code": 0,
        "data": services,
        "total": total,
        "page": page,
        "page_size": page_size
    })


@app.route("/api/services/export", methods=["GET"])
def export_services():
    """导出筛选结果的全部参数（用于批量复制）"""
    module = request.args.get("module", "").strip()
    env = request.args.get("env", "").strip()
    keyword = request.args.get("keyword", "").strip()

    services = db.get_all_for_export(module=module, env=env, keyword=keyword)
    create_params = [s["create_change_params"] for s in services if s["create_change_params"]]
    devflow_params = [s["run_devflow_params"] for s in services if s["run_devflow_params"]]

    return jsonify({
        "code": 0,
        "data": {
            "total": len(services),
            "create_change_params": create_params,
            "run_devflow_params": devflow_params,
        }
    })


@app.route("/api/services/<int:sid>", methods=["GET"])
def get_service(sid):
    """获取单个服务详情"""
    service = db.get_service_by_id(sid)
    if not service:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "data": service})


@app.route("/api/services", methods=["POST"])
def create_service():
    """新增服务"""
    data = request.get_json()
    required = ["business_module", "service_name"]
    for field in required:
        if not data.get(field):
            return jsonify({"code": 400, "message": f"缺少必填字段: {field}"}), 400

    sid = db.create_service(
        business_module=data["business_module"],
        service_name=data["service_name"],
        create_change_params=data.get("create_change_params", ""),
        run_devflow_params=data.get("run_devflow_params", ""),
        env=data.get("env", "中国"),
    )
    return jsonify({"code": 0, "message": "新增成功", "data": {"id": sid}})


@app.route("/api/services/<int:sid>", methods=["PUT"])
def update_service(sid):
    """更新服务"""
    data = request.get_json()
    ok = db.update_service(sid, **data)
    if not ok:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "message": "更新成功"})


@app.route("/api/services/<int:sid>", methods=["DELETE"])
def delete_service(sid):
    """删除服务"""
    ok = db.delete_service(sid)
    if not ok:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "message": "删除成功"})


# ==================== 批量导入 ====================

@app.route("/api/import", methods=["POST"])
def import_excel():
    """从 Excel 导入数据"""
    try:
        import pandas as pd
        filepath = os.path.expanduser(EXCEL_PATH)
        if not os.path.exists(filepath):
            return jsonify({"code": 404, "message": f"找不到文件: {filepath}"}), 404

        df = pd.read_excel(filepath)
        df.columns = ["business_module", "service_name", "create_change_params", "run_devflow_params", "env"]

        count = 0
        for _, row in df.iterrows():
            db.create_service(
                business_module=str(row["business_module"]),
                service_name=str(row["service_name"]),
                create_change_params=str(row["create_change_params"]),
                run_devflow_params=str(row["run_devflow_params"]),
                env=str(row["env"]),
            )
            count += 1

        return jsonify({"code": 0, "message": f"导入成功，共 {count} 条记录"})
    except Exception as e:
        return jsonify({"code": 500, "message": f"导入失败: {str(e)}"}), 500


# ==================== 服务凭证 CRUD ====================

@app.route("/api/credentials", methods=["GET"])
def get_credentials():
    """查询凭证列表（支持 env + 业务名称 name + 关键词 keyword + 密码脱敏）"""
    env = request.args.get("env", "").strip()
    name = request.args.get("name", "").strip()
    keyword = request.args.get("keyword", "").strip()
    ctype = request.args.get("type", "").strip()
    status = request.args.get("status", "").strip()
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))

    items, total = db.get_credentials(env=env, name=name, keyword=keyword, type=ctype, status=status,
                                      page=page, page_size=page_size)
    # 密码脱敏：列表不返回明文，只返回是否已设置
    for it in items:
        it["password"] = "●●●●●●●●" if it.get("password") else ""
    return jsonify({"code": 0, "data": items, "total": total, "page": page, "page_size": page_size})


@app.route("/api/credentials/<int:cid>", methods=["GET"])
def get_credential(cid):
    """获取单条凭证（密码脱敏返回）"""
    item = db.get_credential_by_id(cid)
    if not item:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    if item.get("password"):
        item["password"] = "●●●●●●●●"
    return jsonify({"code": 0, "data": item})


@app.route("/api/credentials", methods=["POST"])
def create_credential():
    """新增凭证（密码加密存储）"""
    from crypto import encrypt_password
    data = request.get_json()
    if not data.get("service_name"):
        return jsonify({"code": 400, "message": "缺少必填字段: service_name"}), 400
    # 密码加密后再入库
    if data.get("password"):
        data["password"] = encrypt_password(data["password"])
    cid = db.create_credential(**data)
    db.add_activity(session.get("username", ""), "create", "服务凭证",
                    f"新增凭证「{data.get('service_name', '')}」")
    return jsonify({"code": 0, "message": "新增成功", "data": {"id": cid}})


@app.route("/api/credentials/<int:cid>", methods=["PUT"])
def update_credential(cid):
    """更新凭证（密码为空不覆盖原密码，非空则加密）"""
    from crypto import encrypt_password
    data = request.get_json()
    if "password" in data:
        if data["password"] in (None, "", "●●●●●●●●"):
            # 未修改密码：移除字段不更新
            data.pop("password", None)
        else:
            data["password"] = encrypt_password(data["password"])
    ok = db.update_credential(cid, **data)
    if not ok:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    db.add_activity(session.get("username", ""), "update", "服务凭证", f"更新凭证#{cid}")
    return jsonify({"code": 0, "message": "更新成功"})


@app.route("/api/credentials/<int:cid>", methods=["DELETE"])
def delete_credential(cid):
    """删除凭证"""
    ok = db.delete_credential(cid)
    if not ok:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    db.add_activity(session.get("username", ""), "delete", "服务凭证", f"删除凭证#{cid}")
    return jsonify({"code": 0, "message": "删除成功"})


@app.route("/api/credential-envs", methods=["GET"])
def get_credential_envs():
    """获取凭证环境列表"""
    envs = db.get_credential_envs()
    return jsonify({"code": 0, "data": envs})


@app.route("/api/credential-service-names", methods=["GET"])
def get_credential_service_names():
    """获取凭证业务名称列表（datalist 下拉搜索）"""
    names = db.get_credential_service_names()
    return jsonify({"code": 0, "data": names})


@app.route("/api/credential-providers", methods=["GET"])
def get_credential_providers():
    """获取服务供应商列表（datalist 下拉搜索）"""
    providers = db.get_credential_providers()
    return jsonify({"code": 0, "data": providers})


@app.route("/api/credential-types", methods=["GET"])
def get_credential_types():
    """获取凭证类型列表"""
    types = db.get_credential_types()
    return jsonify({"code": 0, "data": types})


@app.route("/api/credential-owners", methods=["GET"])
def get_credential_owners():
    """获取负责人列表"""
    owners = db.get_credential_owners()
    return jsonify({"code": 0, "data": owners})


# ==================== 域名管理 CRUD ====================

@app.route("/api/domains", methods=["GET"])
def get_domains():
    """查询域名列表"""
    root = request.args.get("root", "").strip()
    keyword = request.args.get("keyword", "").strip()
    env = request.args.get("env", "").strip()
    dtype = request.args.get("type", "").strip()
    region = request.args.get("region", "").strip()
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 50))

    items, total = db.get_domains(root_domain=root, keyword=keyword, env=env, dtype=dtype,
                                   region=region, page=page, page_size=page_size)
    # 格式化 cert_expiry 为 YYYY-MM-DD HH:MM:SS（避免 Flask 默认 RFC 822 格式被前端 slice 截断）
    for it in items:
        it["cert_expiry"] = format_dt(it.get("cert_expiry"))
        if it.get("created_at"): it["created_at"] = format_dt(it["created_at"])
        if it.get("updated_at"): it["updated_at"] = format_dt(it["updated_at"])
    return jsonify({"code": 0, "data": items, "total": total, "page": page, "page_size": page_size})


@app.route("/api/domains/<int:did>", methods=["GET"])
def get_domain(did):
    item = db.get_domain_by_id(did)
    if not item:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "data": item})


@app.route("/api/domains", methods=["POST"])
def create_domain():
    data = request.get_json()
    if not data.get("domain_name"):
        return jsonify({"code": 400, "message": "缺少必填字段: domain_name"}), 400
    did = db.create_domain(**data)
    db.add_activity(session.get("username", ""), "create", "域名管理",
                    f"新增域名「{data.get('domain_name', '')}」")
    return jsonify({"code": 0, "message": "新增成功", "data": {"id": did}})


@app.route("/api/domains/<int:did>", methods=["PUT"])
def update_domain(did):
    data = request.get_json()
    ok = db.update_domain(did, **data)
    if not ok:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    db.add_activity(session.get("username", ""), "update", "域名管理", f"更新域名#{did}")
    return jsonify({"code": 0, "message": "更新成功"})


@app.route("/api/domains/<int:did>", methods=["DELETE"])
def delete_domain(did):
    ok = db.delete_domain(did)
    if not ok:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    db.add_activity(session.get("username", ""), "delete", "域名管理", f"删除域名#{did}")
    return jsonify({"code": 0, "message": "删除成功"})


@app.route("/api/domain-types", methods=["GET"])
def get_domain_types():
    root = request.args.get("root", "").strip()
    types = db.get_domain_types(root_domain=root)
    return jsonify({"code": 0, "data": types})


@app.route("/api/domain-envs", methods=["GET"])
def get_domain_envs():
    root = request.args.get("root", "").strip()
    envs = db.get_domain_envs(root_domain=root)
    return jsonify({"code": 0, "data": envs})


@app.route("/api/root-domains", methods=["GET"])
def get_root_domains():
    roots = db.get_root_domains()
    return jsonify({"code": 0, "data": roots})


@app.route("/api/regions", methods=["GET"])
def get_regions():
    root = request.args.get("root", "").strip()
    regions = db.get_regions(root_domain=root)
    return jsonify({"code": 0, "data": regions})


# ==================== 首页 Dashboard ====================
@app.route("/api/dashboard", methods=["GET"])
@login_required
def dashboard_data():
    """首页聚合数据：统计卡片 + 最近活动"""
    try:
        stats = {
            "services": db.count_rows("service_params"),
            "domains": db.count_rows("domains"),
            "credentials": db.count_rows("service_credentials"),
            "links": db.count_rows("business_links"),
        }
    except Exception:
        stats = {"services": 0, "domains": 0, "credentials": 0, "links": 0}
    recent = db.get_recent_activities(8)
    # 格式化 created_at 为 YYYY-MM-DD HH:MM:SS（避免 Flask 默认 RFC 822 格式被前端 slice 截断）
    for r in recent:
        r["created_at"] = format_dt(r.get("created_at"))
    # 证书到期预警（30 天内）
    cert_alerts = []
    try:
        for c in db.get_cert_alerts(days=30, limit=10):
            exp = c.get("cert_expiry")
            if isinstance(exp, datetime):
                days_left = int((exp - datetime.now()).total_seconds() / 86400)
            elif isinstance(exp, str) and exp:
                try:
                    from datetime import datetime as _dt
                    days_left = int((_dt.fromisoformat(exp) - _dt.now()).total_seconds() / 86400)
                except Exception:
                    days_left = 0
            else:
                days_left = 0
            cert_alerts.append({
                "id": c["id"],
                "domain_name": c["domain_name"],
                "env": c.get("env", ""),
                "region": c.get("region", ""),
                "cert_expiry": format_dt(exp),
                "days_left": days_left,
            })
    except Exception:
        pass
    # 当月日历 + 每日活动数
    try:
        activity_by_day = db.get_activity_by_day(days=31)
    except Exception:
        activity_by_day = {}
    today = datetime.now()
    calendar = {
        "year": today.year,
        "month": today.month,
        "today": today.day,
        "by_day": activity_by_day,
    }
    # 问候语（按当前时间）
    hour = datetime.now().hour
    if hour < 6:
        greeting = "夜深了"
    elif hour < 9:
        greeting = "早上好"
    elif hour < 12:
        greeting = "上午好"
    elif hour < 14:
        greeting = "中午好"
    elif hour < 18:
        greeting = "下午好"
    else:
        greeting = "晚上好"
    username = session.get("display_name") or session.get("username", "")
    return jsonify({
        "code": 0,
        "data": {
            "stats": stats,
            "recent": recent,
            "greeting": greeting,
            "username": username,
            "weekday": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now().weekday()],
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M"),
            "cert_alerts": cert_alerts,
            "calendar": calendar,
            "holidays": get_holidays_map(today.year),
        }
    })


# ==================== 节假日 API（补班/休息提醒） ====================
import json as _json
import time as _time
import urllib.request as _urllib

_HOLIDAY_CACHE = {}          # year -> {MM-DD: {name, isOffDay}}
_HOLIDAY_CACHE_TS = {}       # year -> 拉取时间戳
_HOLIDAY_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "holiday_cache.json")


def _load_holiday_file_cache():
    """启动时加载文件缓存（重启不丢）"""
    try:
        if os.path.exists(_HOLIDAY_CACHE_FILE):
            with open(_HOLIDAY_CACHE_FILE, "r", encoding="utf-8") as f:
                data = _json.load(f)
                for y, items in data.items():
                    _HOLIDAY_CACHE[int(y)] = items
                    _HOLIDAY_CACHE_TS[int(y)] = 0  # 文件缓存视为过期，会重新尝试在线
    except Exception:
        pass


_load_holiday_file_cache()


def _fetch_holidays_online(year):
    """从 timor-api 拉取当年节假日，失败返回 None"""
    try:
        req = _urllib.Request(
            f"https://timor-api.zhheo.com/holiday/list/{year}",
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"},
        )
        with _urllib.urlopen(req, timeout=6) as resp:
            body = resp.read().decode("utf-8", "ignore")
        data = _json.loads(body)
        holiday = (data or {}).get("holiday") or {}
        out = {}
        for mmdd, item in holiday.items():
            if not isinstance(item, dict):
                continue
            out[mmdd] = {"name": str(item.get("name", "")), "isOffDay": bool(item.get("isOffDay", True))}
        if out:
            return out
    except Exception:
        pass
    return None


def _persist_holiday_cache(year, items):
    """把在线数据写文件（下次离线也能用）"""
    try:
        cache = {}
        if os.path.exists(_HOLIDAY_CACHE_FILE):
            with open(_HOLIDAY_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = _json.load(f)
        cache[str(year)] = items
        with open(_HOLIDAY_CACHE_FILE, "w", encoding="utf-8") as f:
            _json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass


def get_holidays_map(year):
    """返回 {MM-DD: {name, isOffDay}}：在线(缓存24h) → 文件缓存 → 内置兜底"""
    y = int(year)
    now = _time.time()
    # 24h 内在线缓存命中
    if y in _HOLIDAY_CACHE and now - _HOLIDAY_CACHE_TS.get(y, 0) < 86400:
        return _HOLIDAY_CACHE[y]
    online = _fetch_holidays_online(y)
    if online:
        _HOLIDAY_CACHE[y] = online
        _HOLIDAY_CACHE_TS[y] = now
        _persist_holiday_cache(y, online)
        return online
    # 在线失败 → 文件缓存（重启前拉过的）
    if y in _HOLIDAY_CACHE:
        return _HOLIDAY_CACHE[y]
    # 最终兜底：内置 JSON（2026 国办安排）
    return get_builtin_holidays(y)


@app.route("/api/holidays/<int:year>", methods=["GET"])
@login_required
def holidays_api(year):
    """节假日列表（补班/休息），供日历渲染"""
    try:
        data = get_holidays_map(year)
        return jsonify({"code": 0, "data": data})
    except Exception as e:
        return jsonify({"code": 1, "message": str(e)})


# ==================== 业务跳转 links ====================
import re as _re

PRESET_LINKS = [
    {"name": "阿里云", "url": "https://account.aliyun.com/login/login.htm",
     "category": "云平台", "description": "阿里云控制台", "sort_order": 1},
    {"name": "腾讯云", "url": "https://cloud.tencent.com/login/subAccount",
     "category": "云平台", "description": "腾讯云子账号登录", "sort_order": 2},
    {"name": "观测云", "url": "https://cn4-auth.guance.com/login/pwd",
     "category": "云平台", "description": "观测云监控平台", "sort_order": 3},
    {"name": "华为云", "url": "https://auth.huaweicloud.com/authui/login.html#/login",
     "category": "云平台", "description": "华为云控制台", "sort_order": 4},
    {"name": "AWS", "url": "https://us-east-2.signin.aws.amazon.com/oauth?client_id=arn%3Aaws%3Asignin%3A%3A%3Aconsole%2Fcanvas&code_challenge=K2dbVGU8SuIFy5-ifD2GSr4cMrcJ07b2jG333kNzm3E&code_challenge_method=SHA-256&response_type=code&redirect_uri=https%3A%2F%2Fconsole.aws.amazon.com%2Fconsole%2Fhome%3Fca-oauth-flow-id%3D2d71%26hashArgs%3D%2523%26isauthcode%3Dtrue%26nc2%3Dh_si%26oauthStart%3D1786505214884%26src%3Dheader-signin%26state%3DhashArgsFromTB_us-east-2_19174b4af576a4b3",
     "category": "云平台", "description": "AWS 控制台 (us-east-2)", "sort_order": 5},
    {"name": "蓝鲸", "url": "https://bkce7.datousoft.com/login",
     "category": "运维平台", "description": "蓝鲸智云 PaaS", "sort_order": 6},
    {"name": "Jarvis", "url": "https://jarvis.jmj1995.com",
     "category": "内部系统", "description": "Jarvis 内部系统", "sort_order": 7},
]


def _valid_link_url(url):
    """URL 白名单校验：仅 http/https，防 javascript: 等协议注入"""
    if not url or len(url) > 500:
        return False
    return bool(_re.match(r"^https?://", url, _re.I))


def _valid_link_color(color):
    """图标颜色校验：HEX 颜色 (#RRGGBB) 或渐变 CSS class），或空字符串"""
    if not color:
        return True
    if len(color) > 100:
        return False
    if color.startswith("#"):
        return bool(_re.match(r"^#[0-9A-Fa-f]{6}$", color))
    return False


@app.route("/api/links", methods=["GET"])
@login_required
def get_links():
    """获取业务跳转链接列表（所有登录用户）"""
    keyword = request.args.get("keyword", "").strip()
    category = request.args.get("category", "").strip()
    include_inactive = request.args.get("all", "") == "1"
    data = db.get_all_links(keyword=keyword, category=category, active_only=not include_inactive)
    return jsonify({"code": 0, "data": data})


@app.route("/api/links/categories", methods=["GET"])
@login_required
def get_link_categories():
    return jsonify({"code": 0, "data": db.get_link_categories()})


@app.route("/api/links/categories", methods=["POST"])
@require_perm("admin")
def add_link_category():
    """新增分类（管理员）"""
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    if not name:
        return jsonify({"code": 1, "message": "分类名称必填"})
    if len(name) > 50:
        return jsonify({"code": 1, "message": "分类名称过长（最多 50 字符）"})
    db.ensure_category(name)
    return jsonify({"code": 0, "data": name, "message": f"分类「{name}」已新增"})


@app.route("/api/links/categories/<path:cat_name>", methods=["DELETE"])
@require_perm("admin")
def delete_link_category(cat_name):
    """删除分类（管理员）：该分类下链接将变为未分类"""
    name = cat_name.strip()
    if not name:
        return jsonify({"code": 1, "message": "分类名称无效"})
    cnt = db.delete_category(name)
    return jsonify({"code": 0, "message": f"分类「{name}」已删除，{cnt} 个链接变为未分类"})


@app.route("/api/links", methods=["POST"])
@require_perm("admin")
def create_link():
    """新增链接（管理员）"""
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()
    url = str(body.get("url", "")).strip()
    if not name or not url:
        return jsonify({"code": 1, "message": "名称和 URL 必填"})
    if not _valid_link_url(url):
        return jsonify({"code": 1, "message": "URL 必须以 http:// 或 https:// 开头"})
    color = str(body.get("color", "")).strip()
    if not _valid_link_color(color):
        return jsonify({"code": 1, "message": "颜色格式无效（需 #RRGGBB）"})
    lid = db.create_link(
        name=name, url=url,
        category=str(body.get("category", "云平台")).strip() or "云平台",
        description=str(body.get("description", "")).strip(),
        color=color,
        sort_order=int(body.get("sort_order", 0) or 0),
        is_active=1 if body.get("is_active", True) else 0,
    )
    db.add_activity(session.get("username", ""), "create", "业务跳转", f"新增链接「{name}」")
    return jsonify({"code": 0, "data": {"id": lid}, "message": "链接已添加"})


@app.route("/api/links/<int:lid>", methods=["PUT"])
@require_perm("admin")
def update_link(lid):
    """更新链接（管理员）"""
    body = request.get_json(silent=True) or {}
    if "url" in body and body["url"]:
        if not _valid_link_url(str(body["url"])):
            return jsonify({"code": 1, "message": "URL 必须以 http:// 或 https:// 开头"})
    if "color" in body and not _valid_link_color(str(body["color"] or "")):
        return jsonify({"code": 1, "message": "颜色格式无效（需 #RRGGBB）"})
    fields = {}
    for k in ["name", "url", "category", "description", "color"]:
        if k in body:
            fields[k] = str(body[k]).strip()
    if "sort_order" in body:
        fields["sort_order"] = int(body["sort_order"] or 0)
    if "is_active" in body:
        fields["is_active"] = 1 if body["is_active"] else 0
    if not fields:
        return jsonify({"code": 1, "message": "无更新字段"})
    ok = db.update_link(lid, **fields)
    if ok:
        db.add_activity(session.get("username", ""), "update", "业务跳转",
                        f"更新链接#{lid}「{fields.get('name', '') or ''}」")
    return jsonify({"code": 0 if ok else 1, "message": "已更新" if ok else "链接不存在"})


@app.route("/api/links/reorder", methods=["POST"])
@require_perm("admin")
def reorder_links():
    """批量重排（拖拽排序）items = [{'id': int, 'sort_order': int}]"""
    body = request.get_json(silent=True) or {}
    items = body.get("items", [])
    if not isinstance(items, list) or not items:
        return jsonify({"code": 1, "message": "items 必填且非空"})
    try:
        normalized = [{"id": int(i["id"]), "sort_order": int(i["sort_order"])} for i in items]
    except (KeyError, TypeError, ValueError):
        return jsonify({"code": 1, "message": "items 格式错误（需 id + sort_order）"})
    db.reorder_links(normalized)
    return jsonify({"code": 0, "message": f"已更新 {len(normalized)} 条排序"})


@app.route("/api/links/categories/reorder", methods=["POST"])
@require_perm("admin")
def reorder_link_categories():
    """批量重排分类顺序 items = [{'name': str, 'sort_order': int}, ...]"""
    body = request.get_json(silent=True) or {}
    items = body.get("items", [])
    if not isinstance(items, list) or not items:
        return jsonify({"code": 1, "message": "items 必填且非空"})
    try:
        normalized = [{"name": str(i["name"]).strip(), "sort_order": int(i["sort_order"])} for i in items]
    except (KeyError, TypeError, ValueError):
        return jsonify({"code": 1, "message": "items 格式错误（需 name + sort_order）"})
    db.reorder_categories(normalized)
    return jsonify({"code": 0, "message": f"已更新 {len(normalized)} 个分类顺序"})


@app.route("/api/links/<int:lid>", methods=["DELETE"])
@require_perm("admin")
def delete_link(lid):
    """删除链接（管理员）"""
    link = db.get_link_by_id(lid)
    ok = db.delete_link(lid)
    if ok:
        db.add_activity(session.get("username", ""), "delete", "业务跳转",
                        f"删除链接「{link['name'] if link else '#' + str(lid)}」")
    return jsonify({"code": 0 if ok else 1, "message": "已删除" if ok else "链接不存在"})


@app.route("/api/links/import-preset", methods=["POST"])
@require_perm("admin")
def import_preset_links():
    """导入预置站点（幂等：按 name upsert）"""
    added = updated = 0
    for item in PRESET_LINKS:
        row = db.get_all_links(keyword=item["name"], active_only=False)
        exists = any(l["name"] == item["name"] for l in row)
        db.upsert_link_by_name(
            item["name"], url=item["url"], category=item["category"],
            description=item["description"], sort_order=item["sort_order"], is_active=1
        )
        if exists:
            updated += 1
        else:
            added += 1
    return jsonify({"code": 0, "message": f"预置站点导入完成：新增 {added}，更新 {updated}"})


@app.route("/api/domains/import", methods=["POST"])
def import_domains():
    """从 Excel 导入域名数据（读取全部子表）"""
    try:
        import pandas as pd
        xlsx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "..", "..", "Downloads", "生产jmj1995.com域名记录.xlsx")
        filepath = os.path.expanduser(xlsx_path)
        if not os.path.exists(filepath):
            return jsonify({"code": 404, "message": f"找不到文件: {filepath}"}), 404

        xls = pd.ExcelFile(filepath)
        # 清空同名 root_domain 数据后导入
        db.delete_domains_by_root("jmj1995.com")

        count = 0
        # 逐个 sheet 读取（每个 sheet 代表一个区域/环境大类）
        for region in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=region)
            # 列名标准化
            df.columns = [str(c).strip() for c in df.columns]
            # 北美 sheet 多了一个 alb域名 列
            cols = list(df.columns)
            if "alb域名" in cols:
                df = df.rename(columns={"alb域名": "alb_domain"})

            # 找到关键列
            service_col = next((c for c in cols if "服务" in c), None)
            domain_col = next((c for c in cols if c == "域名"), None)
            type_col = next((c for c in cols if c == "类型"), None)
            env_col = next((c for c in cols if "域名环境" in c), None)
            progress_col = next((c for c in cols if "证书更新进度" in c), None)
            expiry_col = next((c for c in cols if "新证书到期时间" in c), None)
            notes_col = next((c for c in cols if "备注" in c), None)

            if not domain_col:
                continue

            for _, row in df.iterrows():
                # 处理空 domain
                domain_val = row[domain_col]
                if pd.isna(domain_val) or not str(domain_val).strip():
                    continue

                # 域名类型：cdn 改小写，其他保留原值
                dtype = ""
                if type_col and pd.notna(row[type_col]):
                    dtype = str(row[type_col]).strip()
                    if dtype.upper() == "CDN":
                        dtype = "cdn"

                # 域名环境：cdn 视为域名环境的一类
                env_val = ""
                if env_col and pd.notna(row[env_col]):
                    env_val = str(row[env_col]).strip()

                # 如果类型是 cdn，也作为环境信息保留到 notes 或保留到 type
                # 按用户原意："cdn 只能算作域名环境"，所以 type 留空，env 填 cdn
                if dtype == "cdn":
                    env_val = "cdn"
                    dtype = ""

                expiry = None
                if expiry_col and pd.notna(row[expiry_col]):
                    expiry = str(row[expiry_col])

                db.create_domain(
                    root_domain="jmj1995.com",
                    region=region,                            # 子表名作为大区分类
                    service_name=str(row[service_col]).strip() if service_col and pd.notna(row[service_col]) else "",
                    domain_name=str(domain_val).strip(),
                    domain_type=dtype,
                    env=env_val,
                    cert_progress=str(row[progress_col]).strip() if progress_col and pd.notna(row[progress_col]) else "",
                    cert_expiry=expiry,
                    notes=str(row[notes_col]).strip() if notes_col and pd.notna(row[notes_col]) else "",
                )
                count += 1

        return jsonify({"code": 0, "message": f"导入成功，共 {count} 条记录（覆盖 {len(xls.sheet_names)} 个子表）"})
    except Exception as e:
        return jsonify({"code": 500, "message": f"导入失败: {str(e)}"}), 500


# ==================== 通用：导入 / 导出 / 模板下载 ====================

# ---------- 发版参数 ----------

@app.route("/api/services/export-xlsx", methods=["GET"])
def export_services_xlsx():
    """导出当前筛选的发版参数为 xlsx"""
    module = request.args.get("module", "").strip()
    env = request.args.get("env", "").strip()
    keyword = request.args.get("keyword", "").strip()

    items = db.get_all_for_export(module=module, env=env, keyword=keyword)
    headers = ["业务模块", "服务名称", "创建变更单参数", "运行研发流程参数", "服务环境"]
    rows = [[s["business_module"], s["service_name"], s["create_change_params"],
             s["run_devflow_params"], s["env"]] for s in items]
    fname = f"发版参数_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return excel_response(headers, rows, fname, sheet_name="发版参数")


@app.route("/api/services/template", methods=["GET"])
def services_template():
    """下载发版参数导入模板"""
    headers = ["业务模块", "服务名称", "创建变更单参数", "运行研发流程参数", "服务环境"]
    example = [
        ["会员", "member-admin", "member-admin", "member-admin|cn", "中国"],
        ["会员", "member-taier", "member-taier", "member-taier|cn", "中国"],
        ["点餐小程序", "minipg-taier", "minipg-taier", "minipg-taier|cn", "中国"],
        ["商城", "mall-admin-global", "mall-admin-global", "mall-admin-global|sn", "新加坡"],
    ]
    fname = "发版参数导入模板.xlsx"
    return excel_response(headers, example, fname, sheet_name="发版参数(请按此格式填写)")


# ---------- 网络工具 ----------

import nettools


def _validate_net_host():
    """从请求参数取 host 并校验，返回 (ok, host, error_json)"""
    data = request.get_json(silent=True) or {}
    host = (data.get("host") or request.args.get("host", "")).strip()
    ok, msg, host = nettools.validate_host(host)
    if not ok:
        return False, None, jsonify({"code": 400, "message": msg}), 400
    return True, host, None, None


@app.route("/api/nettools/myip", methods=["GET"])
@login_required
def nettools_myip():
    """本机出口 IP 查询（服务端视角）"""
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.remote_addr or ""
    if not ip:
        return jsonify({"code": 1, "message": "无法获取客户端 IP"})
    return jsonify(nettools.myip_lookup(ip))


@app.route("/api/nettools/ip", methods=["POST"])
@login_required
def nettools_ip():
    """IP 归属地查询"""
    ok, host, err, code = _validate_net_host()
    if not ok:
        return err, code
    return jsonify(nettools.ip_lookup(host))


@app.route("/api/nettools/ping", methods=["POST"])
@login_required
def nettools_ping():
    """PING 检测"""
    ok, host, err, code = _validate_net_host()
    if not ok:
        return err, code
    data = request.get_json(silent=True) or {}
    count = int(data.get("count", 4))
    timeout = int(data.get("timeout", 5))
    count = max(1, min(count, 10))
    timeout = max(1, min(timeout, 10))
    return jsonify(nettools.ping_detect(host, count=count, timeout=timeout))


@app.route("/api/nettools/tcping", methods=["POST"])
@login_required
def nettools_tcping():
    """TCPing 端口连通性测试"""
    ok, host, err, code = _validate_net_host()
    if not ok:
        return err, code
    data = request.get_json(silent=True) or {}
    port = int(data.get("port", 80))
    timeout = int(data.get("timeout", 3))
    port = max(1, min(port, 65535))
    timeout = max(1, min(timeout, 10))
    return jsonify(nettools.tcping(host, port, timeout))


@app.route("/api/nettools/dns", methods=["POST"])
@login_required
def nettools_dns():
    """DNS 记录查询"""
    ok, host, err, code = _validate_net_host()
    if not ok:
        return err, code
    data = request.get_json(silent=True) or {}
    rtype = (data.get("type") or "A").upper()
    dns_server = (data.get("dns_server") or "").strip() or None
    return jsonify(nettools.dns_query(host, rtype, dns_server))


@app.route("/api/nettools/route", methods=["POST"])
@login_required
def nettools_route():
    """路由查询（Traceroute）"""
    ok, host, err, code = _validate_net_host()
    if not ok:
        return err, code
    data = request.get_json(silent=True) or {}
    max_hops = int(data.get("max_hops", 30))
    max_hops = max(3, min(max_hops, 64))
    return jsonify(nettools.route_trace(host, max_hops=max_hops))


@app.route("/api/nettools/mtr", methods=["POST"])
@login_required
def nettools_mtr():
    """MTR 路由去程"""
    ok, host, err, code = _validate_net_host()
    if not ok:
        return err, code
    data = request.get_json(silent=True) or {}
    count = int(data.get("count", 10))
    count = max(3, min(count, 30))
    return jsonify(nettools.mtr_trace(host, count=count))


@app.route("/api/nettools/cdn", methods=["POST"])
@login_required
def nettools_cdn():
    """CDN 服务商识别"""
    ok, host, err, code = _validate_net_host()
    if not ok:
        return err, code
    return jsonify(nettools.cdn_lookup(host))


@app.route("/api/nettools/whois", methods=["POST"])
@login_required
def nettools_whois():
    """Whois 域名注册信息查询（仅格式校验，允许内网/公司私有域名查询公共注册库）"""
    data = request.get_json(silent=True) or {}
    host = (data.get("host") or request.args.get("host", "")).strip()
    ok, msg, host = nettools.validate_host_fmt(host)
    if not ok:
        return jsonify({"code": 400, "message": msg}), 400
    return jsonify(nettools.whois_query(host))


@app.route("/api/nettools/ssl", methods=["POST"])
@login_required
def nettools_ssl():
    """SSL 证书信息 + TLS 协议支持检测（仅格式校验，运维常查公司私有域名证书）"""
    data = request.get_json(silent=True) or {}
    host = (data.get("host") or request.args.get("host", "")).strip()
    ok, msg, host = nettools.validate_host_fmt(host)
    if not ok:
        return jsonify({"code": 400, "message": msg}), 400
    port = int(data.get("port", 443))
    port = max(1, min(port, 65535))
    return jsonify(nettools.ssl_inspect(host, port))


# ---------- 运维小工具 ----------

import opsutils


@app.route("/api/utils/cidr", methods=["POST"])
@login_required
def utils_cidr():
    data = request.get_json(silent=True) or {}
    return jsonify(opsutils.cidr_calc(data.get("cidr", "")))


@app.route("/api/utils/timestamp", methods=["POST"])
@login_required
def utils_timestamp():
    data = request.get_json(silent=True) or {}
    tz = int(data.get("tz", 8))
    return jsonify(opsutils.timestamp_convert(data.get("value", ""), tz))


@app.route("/api/utils/json", methods=["POST"])
@login_required
def utils_json():
    data = request.get_json(silent=True) or {}
    return jsonify(opsutils.json_format(data.get("text", ""), int(data.get("indent", 2))))


@app.route("/api/utils/encode", methods=["POST"])
@login_required
def utils_encode():
    data = request.get_json(silent=True) or {}
    return jsonify(opsutils.encode_hash(data.get("text", ""), data.get("action", "base64_encode"), data.get("algo", "sha256")))


@app.route("/api/utils/webhook", methods=["POST"])
@login_required
def utils_webhook():
    data = request.get_json(silent=True) or {}
    return jsonify(opsutils.webhook_test(data.get("url", ""), data.get("method", "POST"),
                                          data.get("headers") or {}, data.get("body", "")))


@app.route("/api/utils/batch-tcping", methods=["POST"])
@login_required
def utils_batch_tcping():
    data = request.get_json(silent=True) or {}
    return jsonify(opsutils.batch_tcping(data.get("items", [])))


@app.route("/api/utils/http-health", methods=["POST"])
@login_required
def utils_http_health():
    data = request.get_json(silent=True) or {}
    return jsonify(opsutils.http_health(data.get("url", ""), int(data.get("timeout", 10))))


@app.route("/api/utils/cert-monitor", methods=["POST"])
@login_required
def utils_cert_monitor():
    data = request.get_json(silent=True) or {}
    domains = data.get("domains", [])
    if isinstance(domains, str):
        domains = [d.strip() for d in domains.splitlines() if d.strip()]
    return jsonify(opsutils.cert_monitor(domains))


@app.route("/api/utils/yaml-check", methods=["POST"])
@login_required
def utils_yaml_check():
    data = request.get_json(silent=True) or {}
    return jsonify(opsutils.yaml_check(data.get("text", "")))


@app.route("/api/utils/curl", methods=["POST"])
@login_required
def utils_curl():
    data = request.get_json(silent=True) or {}
    return jsonify(opsutils.curl_debug(data.get("command", "")))


# ---------- 服务凭证 ----------

@app.route("/api/credentials/import", methods=["POST"])
def import_credentials_xlsx():
    """从 开发生产服务器信息.xlsx 导入服务凭证（6 个子表 = 6 个环境）

    ⚠️ 安全：密码列（密码/口令/Password）显式跳过，不读取、不导入。
    端口列同时写入 internal_port 与 external_port（保持一致，后续可编辑调整）。
    """
    try:
        import pandas as pd
        xlsx_path = request.json.get("filepath", "") if request.is_json else ""
        if not xlsx_path:
            xlsx_path = os.path.expanduser("~/Downloads/开发生产服务器信息.xlsx")
        filepath = os.path.expanduser(xlsx_path)
        if not os.path.exists(filepath):
            return jsonify({"code": 404, "message": f"找不到文件: {filepath}"}), 404

        xls = pd.ExcelFile(filepath)
        total_count = 0
        env_count = {}

        def _match_col(df, *names):
            """模糊匹配列名：返回第一个存在的列名，找不到返回 None"""
            for n in names:
                if n in df.columns:
                    return n
            return None

        def _to_int(v):
            s = str(v).strip() if v is not None else ""
            return int(float(s)) if s.replace(".", "").isdigit() else None

        def _to_str(v):
            """pandas 空单元格(NaN)/None → 空字符串，避免出现 'nan'"""
            if v is None:
                return ""
            s = str(v).strip()
            return "" if s.lower() in ("nan", "none", "nat") else s

        for env_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=env_name)
            df.columns = [str(c).strip() for c in df.columns]

            svc_col = _match_col(df, "业务名称", "服务名", "业务名", "service_name")
            if not svc_col:
                continue
            count = 0
            for _, row in df.iterrows():
                svc = _to_str(row.get(svc_col))
                if not svc:
                    continue
                # 列匹配（不同子表字段不统一，逐个模糊匹配）
                app_type_col = _match_col(df, "应用类型")
                version_col = _match_col(df, "版本")
                access_url_col = _match_col(df, "服务连接地址", "服务地址", "连接地址")
                int_url_col = _match_col(df, "内网连接地址", "内网地址", "私网地址")
                ext_url_col = _match_col(df, "web访问链接", "Web访问链接", "公网地址", "地址")
                port_col = _match_col(df, "端口", "服务连接端口", "连接端口")
                user_col = _match_col(df, "账号", "用户名", "用户")
                notes_col = _match_col(df, "备注")

                # 端口：同时写入内网/公网端口（保持一致，后续可编辑调整）
                port = _to_int(row.get(port_col)) if port_col else None

                db.create_credential(
                    env=env_name,
                    service_name=svc,
                    app_type=_to_str(row.get(app_type_col)) if app_type_col else "",
                    version=_to_str(row.get(version_col)) if version_col else "",
                    access_url=_to_str(row.get(access_url_col)) if access_url_col else "",
                    internal_url=_to_str(row.get(int_url_col)) if int_url_col else "",
                    external_url=_to_str(row.get(ext_url_col)) if ext_url_col else "",
                    internal_port=port,
                    external_port=port,
                    username=_to_str(row.get(user_col)) if user_col else "",
                    # ⚠️ 密码列显式跳过，不导入（敏感信息由用户手动录入）
                    notes=_to_str(row.get(notes_col)) if notes_col else "",
                )
                count += 1
            if count:
                env_count[env_name] = count
                total_count += count

        return jsonify({"code": 0, "message": f"导入成功，共 {total_count} 条凭证", "data": env_count})
    except Exception as e:
        return jsonify({"code": 500, "message": f"导入失败: {str(e)}"}), 500


@app.route("/api/credentials/export", methods=["GET"])
def export_credentials_xlsx():
    """导出当前筛选的凭证为 xlsx（密码列导出为 ●●●●，不含明文）"""
    env = request.args.get("env", "").strip()
    name = request.args.get("name", "").strip()
    keyword = request.args.get("keyword", "").strip()
    ctype = request.args.get("type", "").strip()
    status = request.args.get("status", "").strip()

    items = db.get_credentials(env=env, name=name, keyword=keyword, type=ctype, status=status, page=1, page_size=10000)[0]
    headers = ["环境", "业务名称", "应用类型", "版本", "服务连接地址", "用户名", "密码",
               "内网地址", "内网端口", "公网地址", "公网端口", "备注"]
    data = [[r["env"], r["service_name"], r["app_type"], r["version"], r["access_url"], r["username"],
             "●●●●●●●●" if r["password"] else "",
             r["internal_url"], r["internal_port"],
             r["external_url"], r["external_port"], r["notes"]] for r in items]
    fname = f"服务凭证_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return excel_response(headers, data, fname, sheet_name="服务凭证")


@app.route("/api/credentials/template", methods=["GET"])
def credentials_template():
    """下载服务凭证导入模板"""
    headers = ["服务名", "凭证类型", "访问链接", "用户名", "密码",
               "SSH私钥", "API Token", "内网地址", "内网端口",
               "公网地址", "公网端口", "数据库名", "负责人", "过期时间", "状态", "备注"]
    example = [
        ["member-admin", "用户名密码", "https://admin.example.com", "admin", "your_password",
         "", "", "http://10.0.1.50", 8080, "https://api.example.com", 443, "",
         "张三", "2026-12-31", "正常", "测试凭证"],
        ["gateway", "API Token", "https://gateway.example.com", "", "",
         "", "sk-abc123def456", "http://10.0.0.1", 80, "", "", "",
         "李四", "", "正常", "统一网关"],
        ["oms-server", "SSH密钥", "ssh://oms", "deploy", "",
         "-----BEGIN OPENSSH PRIVATE KEY-----\nxxx\n-----END OPENSSH PRIVATE KEY-----",
         "", "10.0.5.20", 22, "", "", "",
         "王五", "", "正常", "供应链 OMS"],
    ]
    fname = "服务凭证导入模板.xlsx"
    return excel_response(headers, example, fname, sheet_name="服务凭证(请按此格式填写)")


# ---------- 域名 ----------

@app.route("/api/domains/export", methods=["GET"])
def export_domains_xlsx():
    """导出当前筛选的域名为 xlsx"""
    root = request.args.get("root", "").strip()
    keyword = request.args.get("keyword", "").strip()
    env = request.args.get("env", "").strip()
    dtype = request.args.get("type", "").strip()
    region = request.args.get("region", "").strip()

    rows = db.get_all_domains_for_export(root_domain=root, keyword=keyword, env=env, dtype=dtype, region=region)

    headers = ["大区", "服务", "域名", "域名类型", "域名环境", "证书更新进度", "新证书到期时间", "备注"]
    data = [[r["region"], r["service_name"], r["domain_name"], r["domain_type"],
             r["env"], r["cert_progress"], format_dt(r["cert_expiry"]), r["notes"]] for r in rows]
    fname = f"域名_{root or 'all'}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return excel_response(headers, data, fname, sheet_name="域名")


@app.route("/api/domains/template", methods=["GET"])
def domains_template():
    """下载域名导入模板"""
    headers = ["大区", "服务", "域名", "域名类型", "域名环境", "证书更新进度", "新证书到期时间", "备注"]
    example = [
        ["中国", "gateway", "gateway.jmj1995.com", "apisix", "生产ACK集群", "已完成", "2027-01-06 23:59:59", ""],
        ["中国", "n9e", "n9e.jmj1995.com", "nginx", "ECS", "已完成", "2027-01-06 23:59:59", "ack-ops-nginx"],
        ["新加坡", "minipg-taier-singapore", "mall-minipg-taier-singapore", "apisix", "生产新加坡ACK集群", "已完成", "2027-01-06 23:59:59", ""],
        ["北美", "aws-member", "aws-member.example.com", "alb", "生产Amazon EKS\u200c集群", "已完成", "2027-01-06 23:59:59", ""],
        ["私有云", "internal-svc", "internal.jmj1995.com", "apisix", "超融合虚机", "已完成", "2027-01-06 23:59:59", ""],
    ]
    fname = "域名导入模板.xlsx"
    return excel_response(headers, example, fname, sheet_name="域名(请按此格式填写)")


# ---------- 云效创建变更单 ----------

@app.route("/api/ci-orders", methods=["GET"])
def get_ci_orders():
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))
    items, total = db.get_ci_orders(
        keyword=request.args.get("keyword", "").strip(),
        env=request.args.get("env", "").strip(),
        page=page,
        page_size=page_size,
    )
    return jsonify({"code": 0, "data": items, "total": total, "page": page, "page_size": page_size})

@app.route("/api/ci-orders/<int:cid>", methods=["GET"])
def get_ci_order(cid):
    item = db._ci_get_by_id("ci_orders", cid)
    if not item: return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "data": item})

@app.route("/api/ci-orders", methods=["POST"])
def create_ci_order():
    data = request.get_json()
    if not data.get("delivery_service"): return jsonify({"code": 400, "message": "缺少服务名"}), 400
    cid = db._ci_create("ci_orders", **data)
    return jsonify({"code": 0, "data": {"id": cid}})

@app.route("/api/ci-orders/<int:cid>", methods=["PUT"])
def update_ci_order(cid):
    ok = db._ci_update("ci_orders", cid, **request.get_json())
    if not ok: return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "message": "更新成功"})

@app.route("/api/ci-orders/<int:cid>", methods=["DELETE"])
def delete_ci_order(cid):
    if not db._ci_delete("ci_orders", cid): return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "message": "删除成功"})

@app.route("/api/ci-orders/envs", methods=["GET"])
def ci_orders_envs():
    return jsonify({"code": 0, "data": db._ci_envs("ci_orders")})

@app.route("/api/ci-orders/import", methods=["POST"])
def import_ci_orders():
    try:
        import pandas as pd
        fp = os.path.expanduser("~/Downloads/云效创建变更单.xlsx")
        df = pd.read_excel(fp)
        df.columns = ["delivery_service", "env", "branch", "repo_sn"]
        # 清空后导入（幂等覆盖）
        db._ci_delete_all("ci_orders")
        count = 0
        for _, row in df.iterrows():
            db._ci_create("ci_orders", delivery_service=str(row["delivery_service"]),
                          env=str(row["env"]), branch=str(row["branch"]), repo_sn=str(row["repo_sn"]))
            count += 1
        return jsonify({"code": 0, "message": f"导入成功，共 {count} 条记录"})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)}), 500

@app.route("/api/ci-orders/export", methods=["GET"])
def export_ci_orders():
    items, _ = db.get_ci_orders(keyword=request.args.get("keyword","").strip(), env=request.args.get("env","").strip(), page=1, page_size=10000)
    headers = ["应用交付服务", "创建变更单环境", "生产发版分支", "应用代码仓库标识符(appCodeRepoSn)"]
    rows = [[i["delivery_service"], i["env"], i["branch"], i["repo_sn"]] for i in items]
    return excel_response(headers, rows, f"云效创建变更单_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", sheet_name="创建变更单")

@app.route("/api/ci-orders/template", methods=["GET"])
def ci_orders_template():
    headers = ["应用交付服务", "创建变更单环境", "生产发版分支", "应用代码仓库标识符(appCodeRepoSn)"]
    example = [["minipg-taier", "中国", "master", "67e20e77c3104bd3af699d591e80dd34"], ["aws-member", "北美", "north-america", "xxx"]]
    return excel_response(headers, example, "云效创建变更单_导入模板.xlsx", sheet_name="创建变更单(请按此格式填写)")


# ---------- 云效运行研发流程 ----------

@app.route("/api/ci-devflow", methods=["GET"])
def get_ci_devflows():
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))
    items, total = db.get_ci_devflows(
        keyword=request.args.get("keyword", "").strip(),
        env=request.args.get("env", "").strip(),
        page=page,
        page_size=page_size,
    )
    return jsonify({"code": 0, "data": items, "total": total, "page": page, "page_size": page_size})

@app.route("/api/ci-devflow/<int:cid>", methods=["GET"])
def get_ci_devflow(cid):
    item = db._ci_get_by_id("ci_devflow", cid)
    if not item: return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "data": item})

@app.route("/api/ci-devflow", methods=["POST"])
def create_ci_devflow():
    data = request.get_json()
    if not data.get("delivery_service"): return jsonify({"code": 400, "message": "缺少服务名"}), 400
    cid = db._ci_create("ci_devflow", **data)
    return jsonify({"code": 0, "data": {"id": cid}})

@app.route("/api/ci-devflow/<int:cid>", methods=["PUT"])
def update_ci_devflow(cid):
    ok = db._ci_update("ci_devflow", cid, **request.get_json())
    if not ok: return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "message": "更新成功"})

@app.route("/api/ci-devflow/<int:cid>", methods=["DELETE"])
def delete_ci_devflow(cid):
    if not db._ci_delete("ci_devflow", cid): return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "message": "删除成功"})

@app.route("/api/ci-devflow/envs", methods=["GET"])
def ci_devflow_envs():
    return jsonify({"code": 0, "data": db._ci_envs("ci_devflow")})

@app.route("/api/ci-devflow/import", methods=["POST"])
def import_ci_devflow():
    try:
        import pandas as pd
        fp = os.path.expanduser("~/Downloads/云效运行研发流程.xlsx")
        df = pd.read_excel(fp)
        df.columns = ["delivery_service", "env", "wf_sn", "stage_sn"]
        db._ci_delete_all("ci_devflow")
        count = 0
        for _, row in df.iterrows():
            db._ci_create("ci_devflow", delivery_service=str(row["delivery_service"]),
                          env=str(row["env"]), wf_sn=str(row["wf_sn"]), stage_sn=str(row["stage_sn"]))
            count += 1
        return jsonify({"code": 0, "message": f"导入成功，共 {count} 条记录"})
    except Exception as e:
        return jsonify({"code": 500, "message": str(e)}), 500

@app.route("/api/ci-devflow/export", methods=["GET"])
def export_ci_devflow():
    items, _ = db.get_ci_devflows(keyword=request.args.get("keyword","").strip(), env=request.args.get("env","").strip(), page=1, page_size=10000)
    headers = ["应用交付服务", "研发流程环境", "发布流程唯一序列号(releaseWorkflowSn)", "发布流程阶段唯一序列号(releaseStageSn)"]
    rows = [[i["delivery_service"], i["env"], i["wf_sn"], i["stage_sn"]] for i in items]
    return excel_response(headers, rows, f"云效运行研发流程_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx", sheet_name="运行研发流程")

@app.route("/api/ci-devflow/template", methods=["GET"])
def ci_devflow_template():
    headers = ["应用交付服务", "研发流程环境", "发布流程唯一序列号(releaseWorkflowSn)", "发布流程阶段唯一序列号(releaseStageSn)"]
    example = [["aws-member", "北美", "b77477fc3d8148c9b7c1f8b6cd01649d", "6437ee23dfea478285da9d4d62d3a2e5"], ["member-taier", "中国", "xxx", "xxx"]]
    return excel_response(headers, example, "云效运行研发流程_导入模板.xlsx", sheet_name="运行研发流程(请按此格式填写)")


# ==================== 用户管理 API（仅管理员可访问）====================

@app.route("/api/users", methods=["GET"])
@require_perm("admin")
def list_users():
    users = db.get_users()
    return jsonify({"code": 0, "data": users})


@app.route("/api/users", methods=["POST"])
@require_perm("admin")
def add_user():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"code": 400, "message": "用户名和密码不能为空"}), 400
    try:
        uid = db.create_user(username, password,
                             data.get("display_name", username),
                             data.get("permissions", "release,credentials,domains"))
        return jsonify({"code": 0, "data": {"id": uid}})
    except Exception as e:
        return jsonify({"code": 500, "message": f"创建失败: {e}"}), 500


@app.route("/api/users/<int:uid>", methods=["PUT"])
@require_perm("admin")
def edit_user(uid):
    data = request.get_json()
    if not db.update_user(uid, **data):
        return jsonify({"code": 404, "message": "用户不存在"}), 404
    return jsonify({"code": 0, "message": "更新成功"})


@app.route("/api/users/<int:uid>/reset-pwd", methods=["POST"])
@require_perm("admin")
def reset_user_pwd(uid):
    data = request.get_json()
    pwd = data.get("password", "").strip()
    if not pwd:
        return jsonify({"code": 400, "message": "密码不能为空"}), 400
    db.reset_password(uid, pwd)
    return jsonify({"code": 0, "message": "密码重置成功"})


@app.route("/api/change-password", methods=["POST"])
def change_my_password():
    """当前登录用户修改自己的密码（需要验证旧密码）"""
    if "username" not in session:
        return jsonify({"code": 401, "message": "请先登录"}), 401
    data = request.get_json()
    old_pwd = (data.get("old_password") or "").strip()
    new_pwd = (data.get("new_password") or "").strip()
    if not old_pwd or not new_pwd:
        return jsonify({"code": 400, "message": "请填写旧密码和新密码"}), 400
    if len(new_pwd) < 6:
        return jsonify({"code": 400, "message": "新密码至少 6 位"}), 400
    user = db.get_user_by_username(session["username"])
    if not user:
        return jsonify({"code": 404, "message": "用户不存在"}), 404
    # 验证旧密码
    if hash_password(old_pwd) != user["password_hash"]:
        return jsonify({"code": 400, "message": "当前密码不正确"}), 400
    # 修改密码
    db.reset_password(user["id"], new_pwd)
    return jsonify({"code": 0, "message": "密码修改成功"})


@app.route("/api/users/<int:uid>", methods=["DELETE"])
@require_perm("admin")
def remove_user(uid):
    if uid == 1:
        return jsonify({"code": 400, "message": "不能删除管理员账号"}), 400
    db.delete_user(uid)
    return jsonify({"code": 0, "message": "删除成功"})

# ==================== 启动 ====================

if __name__ == "__main__":
    print(f"数据库路径: {DB_PATH}")
    print(f"Excel路径:  {EXCEL_PATH}")
    print("服务启动中... http://127.0.0.1:5001")
    app.run(debug=False, host="0.0.0.0", port=5001, use_reloader=False)
