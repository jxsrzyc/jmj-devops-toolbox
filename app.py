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

app = Flask(__name__)
CORS(app, supports_credentials=True)
app.secret_key = "lanqi-svc-params-secret-2026"

# 数据库路径（可通过环境变量覆盖，适配 Docker/K8s）
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))
EXCEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "Downloads", "蓝鲸云效服务发版参数列表.xlsx")


# ==================== 页面路由 ====================

@app.route("/")
@login_required
def index():
    """首页 — 已登录才能访问"""
    return render_template("index.html", **get_user_context())


@app.route("/login", methods=["GET", "POST"])
def login_page():
    """登录页面"""
    if request.method == "POST":
        data = request.get_json()
        username = data.get("username", "").strip()
        password = data.get("password", "").strip()
        if not username or not password:
            return jsonify({"code": 400, "message": "用户名和密码不能为空"}), 400
        user = db.get_user_by_username(username)
        if not user:
            return jsonify({"code": 401, "message": "用户名或密码错误"}), 401
        from auth import verify_password
        if not verify_password(password, user["password_hash"]):
            return jsonify({"code": 401, "message": "用户名或密码错误"}), 401
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["display_name"] = user["display_name"] or user["username"]
        session["permissions"] = user["permissions"]
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
    """查询凭证列表"""
    keyword = request.args.get("keyword", "").strip()
    ctype = request.args.get("type", "").strip()
    status = request.args.get("status", "").strip()
    page = int(request.args.get("page", 1))
    page_size = int(request.args.get("page_size", 20))

    items, total = db.get_credentials(keyword=keyword, type=ctype, status=status,
                                       page=page, page_size=page_size)
    return jsonify({"code": 0, "data": items, "total": total, "page": page, "page_size": page_size})


@app.route("/api/credentials/<int:cid>", methods=["GET"])
def get_credential(cid):
    """获取单条凭证"""
    item = db.get_credential_by_id(cid)
    if not item:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "data": item})


@app.route("/api/credentials", methods=["POST"])
def create_credential():
    """新增凭证"""
    data = request.get_json()
    if not data.get("service_name"):
        return jsonify({"code": 400, "message": "缺少必填字段: service_name"}), 400
    cid = db.create_credential(**data)
    return jsonify({"code": 0, "message": "新增成功", "data": {"id": cid}})


@app.route("/api/credentials/<int:cid>", methods=["PUT"])
def update_credential(cid):
    """更新凭证"""
    data = request.get_json()
    ok = db.update_credential(cid, **data)
    if not ok:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "message": "更新成功"})


@app.route("/api/credentials/<int:cid>", methods=["DELETE"])
def delete_credential(cid):
    """删除凭证"""
    ok = db.delete_credential(cid)
    if not ok:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "message": "删除成功"})


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
    return jsonify({"code": 0, "message": "新增成功", "data": {"id": did}})


@app.route("/api/domains/<int:did>", methods=["PUT"])
def update_domain(did):
    data = request.get_json()
    ok = db.update_domain(did, **data)
    if not ok:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
    return jsonify({"code": 0, "message": "更新成功"})


@app.route("/api/domains/<int:did>", methods=["DELETE"])
def delete_domain(did):
    ok = db.delete_domain(did)
    if not ok:
        return jsonify({"code": 404, "message": "记录不存在"}), 404
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
        import sqlite3
        DB = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))
        conn = sqlite3.connect(DB)
        conn.execute("DELETE FROM domains WHERE root_domain=?", ("jmj1995.com",))
        conn.commit()
        conn.close()

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


# ---------- 服务凭证 ----------

@app.route("/api/credentials/import", methods=["POST"])
def import_credentials_xlsx():
    """从 xlsx 导入凭证（增量添加）"""
    try:
        import pandas as pd
        xlsx_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "..", "..", "..", "Downloads", "服务凭证导入模板.xlsx")
        if "filepath" in request.json:
            xlsx_path = request.json["filepath"]
        filepath = os.path.expanduser(xlsx_path)
        if not os.path.exists(filepath):
            return jsonify({"code": 404, "message": f"找不到文件: {filepath}"}), 404

        df = pd.read_excel(filepath)
        expected = ["服务名", "凭证类型", "访问链接", "用户名", "密码",
                    "SSH私钥", "API Token", "内网地址", "内网端口",
                    "公网地址", "公网端口", "数据库名", "负责人", "过期时间", "状态", "备注"]
        df.columns = [str(c).strip() for c in df.columns]
        # 补齐缺失列
        for col in expected:
            if col not in df.columns:
                df[col] = ""

        count = 0
        for _, row in df.iterrows():
            svc = str(row.get("服务名", "")).strip()
            if not svc:
                continue
            db.create_credential(
                service_name=svc,
                credential_type=str(row.get("凭证类型", "用户名密码")),
                access_url=str(row.get("访问链接", "")),
                username=str(row.get("用户名", "")),
                password=str(row.get("密码", "")),
                ssh_key=str(row.get("SSH私钥", "")),
                api_token=str(row.get("API Token", "")),
                internal_url=str(row.get("内网地址", "")),
                internal_port=int(row["内网端口"]) if str(row.get("内网端口", "")).strip().isdigit() else None,
                external_url=str(row.get("公网地址", "")),
                external_port=int(row["公网端口"]) if str(row.get("公网端口", "")).strip().isdigit() else None,
                db_name=str(row.get("数据库名", "")),
                owner=str(row.get("负责人", "")),
                expires_at=str(row.get("过期时间", "")) or None,
                status=str(row.get("状态", "正常")) or "正常",
                notes=str(row.get("备注", "")),
            )
            count += 1

        return jsonify({"code": 0, "message": f"导入成功，共 {count} 条凭证"})
    except Exception as e:
        return jsonify({"code": 500, "message": f"导入失败: {str(e)}"}), 500


@app.route("/api/credentials/export", methods=["GET"])
def export_credentials_xlsx():
    """导出当前筛选的凭证为 xlsx"""
    keyword = request.args.get("keyword", "").strip()
    ctype = request.args.get("type", "").strip()
    status = request.args.get("status", "").strip()

    items = db.get_credentials(keyword=keyword, type=ctype, status=status, page=1, page_size=10000)[0]
    headers = ["服务名", "凭证类型", "访问链接", "用户名", "密码",
               "SSH私钥", "API Token", "内网地址", "内网端口",
               "公网地址", "公网端口", "数据库名", "负责人", "过期时间", "状态", "备注"]
    data = [[r["service_name"], r["credential_type"], r["access_url"], r["username"], r["password"],
             r["ssh_key"], r["api_token"], r["internal_url"], r["internal_port"],
             r["external_url"], r["external_port"], r["db_name"], r["owner"],
             format_dt(r["expires_at"]), r["status"], r["notes"]] for r in items]
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

    conditions, params = [], []
    if root: conditions.append("root_domain = ?"); params.append(root)
    if region: conditions.append("region = ?"); params.append(region)
    if keyword:
        conditions.append("(domain_name LIKE ? OR service_name LIKE ?)")
        kw = f"%{keyword}%"; params.extend([kw, kw])
    if env: conditions.append("env = ?"); params.append(env)
    if dtype: conditions.append("domain_type = ?"); params.append(dtype)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""

    import sqlite3
    DB = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(f"SELECT * FROM domains{where} ORDER BY region, domain_type, id", params).fetchall()
    conn.close()

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
        db._ci_delete("ci_orders", 0)  # won't actually delete anything
        # 清空
        with __import__("sqlite3").connect(__import__("os").environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))) as conn:
            conn.execute("DELETE FROM ci_orders"); conn.commit()
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
        with __import__("sqlite3").connect(__import__("os").environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))) as conn:
            conn.execute("DELETE FROM ci_devflow"); conn.commit()
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
