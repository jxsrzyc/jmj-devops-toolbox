"""数据库操作模块 - SQLite"""

import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))


def init_db():
    """初始化数据库表"""
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS service_params (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                business_module TEXT NOT NULL,
                service_name TEXT NOT NULL,
                create_change_params TEXT DEFAULT '',
                run_devflow_params TEXT DEFAULT '',
                env TEXT DEFAULT '中国',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_module ON service_params(business_module);
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_service ON service_params(service_name);
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS service_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL,
                credential_type TEXT DEFAULT '用户名密码',
                access_url TEXT DEFAULT '',
                username TEXT DEFAULT '',
                password TEXT DEFAULT '',
                ssh_key TEXT DEFAULT '',
                api_token TEXT DEFAULT '',
                internal_url TEXT DEFAULT '',
                internal_port INTEGER,
                external_url TEXT DEFAULT '',
                external_port INTEGER,
                db_name TEXT DEFAULT '',
                owner TEXT DEFAULT '',
                expires_at DATE,
                status TEXT DEFAULT '正常',
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS domains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                root_domain TEXT NOT NULL,
                region TEXT DEFAULT '',
                service_name TEXT DEFAULT '',
                domain_name TEXT NOT NULL,
                domain_type TEXT DEFAULT '',
                env TEXT DEFAULT '',
                cert_progress TEXT DEFAULT '已完成',
                cert_expiry DATETIME,
                notes TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_domains_root ON domains(root_domain);
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_domains_domain ON domains(domain_name);
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ci_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_service TEXT NOT NULL,
                env TEXT DEFAULT '',
                branch TEXT DEFAULT '',
                repo_sn TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ci_orders_service ON ci_orders(delivery_service);
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ci_devflow (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                delivery_service TEXT NOT NULL,
                env TEXT DEFAULT '',
                wf_sn TEXT DEFAULT '',
                stage_sn TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ci_devflow_service ON ci_devflow(delivery_service);
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT DEFAULT '',
                permissions TEXT DEFAULT '*',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
        """)
        conn.commit()

        # 默认 admin 账号
        from auth import hash_password
        conn.execute("""
            INSERT OR IGNORE INTO users (username, password_hash, display_name, permissions, is_active)
            VALUES ('admin', ?, '管理员', '*', 1)
        """, (hash_password("admin123"),))
        conn.commit()


@contextmanager
def get_conn():
    """获取数据库连接上下文"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


class Database:
    """数据库操作封装"""

    # ---- 业务模块 ----

    def get_all_modules(self):
        """获取所有业务模块（去重排序）"""
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT business_module FROM service_params ORDER BY business_module"
            ).fetchall()
            return [r["business_module"] for r in rows]

    # ---- 服务参数 CRUD ----

    def get_services(self, module="", keyword="", env="", page=1, page_size=50):
        """查询服务列表（分页），支持按业务模块、环境、关键词筛选"""
        conditions = []
        params = []

        if module:
            conditions.append("business_module = ?")
            params.append(module)
        if env:
            conditions.append("env = ?")
            params.append(env)
        if keyword:
            conditions.append("(service_name LIKE ? OR create_change_params LIKE ? OR run_devflow_params LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw])

        where = " WHERE " + " AND ".join(conditions) if conditions else ""

        with get_conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) as cnt FROM service_params{where}", params).fetchone()["cnt"]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM service_params{where} ORDER BY id LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()
            return [dict(r) for r in rows], total

    def get_all_for_export(self, module="", env="", keyword=""):
        """查询全部符合条件的记录（不分页，供导出用）"""
        conditions = []
        params = []

        if module:
            conditions.append("business_module = ?")
            params.append(module)
        if env:
            conditions.append("env = ?")
            params.append(env)
        if keyword:
            conditions.append("(service_name LIKE ? OR create_change_params LIKE ? OR run_devflow_params LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw])

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM service_params{where} ORDER BY id", params
            ).fetchall()
            return [dict(r) for r in rows]

    def get_envs(self):
        """获取所有环境列表（去重）"""
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT env FROM service_params ORDER BY env"
            ).fetchall()
            return [r["env"] for r in rows]

    # ---- 服务凭证 CRUD ----

    def get_credentials(self, keyword="", type="", status="", page=1, page_size=20):
        """查询凭证列表"""
        conditions, params = [], []
        if keyword:
            conditions.append("(service_name LIKE ? OR owner LIKE ? OR notes LIKE ? OR access_url LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw, kw])
        if type:
            conditions.append("credential_type = ?")
            params.append(type)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with get_conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) as cnt FROM service_credentials{where}", params).fetchone()["cnt"]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM service_credentials{where} ORDER BY id LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()
            return [dict(r) for r in rows], total

    def get_credential_by_id(self, cid):
        """获取单条凭证"""
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM service_credentials WHERE id=?", (cid,)).fetchone()
            return dict(row) if row else None

    def create_credential(self, **fields):
        """新增凭证"""
        allowed = ["service_name", "credential_type", "access_url", "username", "password",
                   "ssh_key", "api_token", "internal_url", "internal_port", "external_url",
                   "external_port", "db_name", "owner", "expires_at", "status", "notes"]
        cols = ["service_name"]
        vals = [fields.get("service_name", "")]
        for f in allowed[1:]:
            cols.append(f)
            vals.append(fields.get(f, ""))

        placeholders = ",".join(["?"] * len(cols))
        col_str = ",".join(cols)
        with get_conn() as conn:
            cursor = conn.execute(
                f"INSERT INTO service_credentials ({col_str}) VALUES ({placeholders})", vals
            )
            conn.commit()
            return cursor.lastrowid

    def update_credential(self, cid, **fields):
        """更新凭证"""
        allowed = ["service_name", "credential_type", "access_url", "username", "password",
                   "ssh_key", "api_token", "internal_url", "internal_port", "external_url",
                   "external_port", "db_name", "owner", "expires_at", "status", "notes"]
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [cid]
        with get_conn() as conn:
            cursor = conn.execute(
                f"UPDATE service_credentials SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                values
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_credential(self, cid):
        """删除凭证"""
        with get_conn() as conn:
            cursor = conn.execute("DELETE FROM service_credentials WHERE id=?", (cid,))
            conn.commit()
            return cursor.rowcount > 0

    def get_credential_types(self):
        """获取凭证类型列表（去重）"""
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT credential_type FROM service_credentials WHERE credential_type != '' ORDER BY credential_type"
            ).fetchall()
            return [r["credential_type"] for r in rows]

    def get_credential_owners(self):
        """获取负责人列表（去重）"""
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT owner FROM service_credentials WHERE owner != '' ORDER BY owner"
            ).fetchall()
            return [r["owner"] for r in rows]

    # ---- 域名管理 CRUD ----

    def get_domains(self, root_domain="", keyword="", env="", dtype="", region="", page=1, page_size=50):
        """查询域名列表"""
        conditions, params = [], []
        if root_domain:
            conditions.append("root_domain = ?")
            params.append(root_domain)
        if region:
            conditions.append("region = ?")
            params.append(region)
        if keyword:
            conditions.append("(domain_name LIKE ? OR service_name LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw])
        if env:
            conditions.append("env = ?")
            params.append(env)
        if dtype:
            conditions.append("domain_type = ?")
            params.append(dtype)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with get_conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) as cnt FROM domains{where}", params).fetchone()["cnt"]
            offset = (page - 1) * page_size
            rows = conn.execute(
                f"SELECT * FROM domains{where} ORDER BY region, domain_type, id LIMIT ? OFFSET ?",
                params + [page_size, offset]
            ).fetchall()
            return [dict(r) for r in rows], total

    def get_domain_by_id(self, did):
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM domains WHERE id=?", (did,)).fetchone()
            return dict(row) if row else None

    def create_domain(self, **fields):
        allowed = ["root_domain", "region", "service_name", "domain_name", "domain_type",
                   "env", "cert_progress", "cert_expiry", "notes"]
        vals = [fields.get(f, "") for f in allowed]
        with get_conn() as conn:
            cursor = conn.execute(
                f"INSERT INTO domains ({','.join(allowed)}) VALUES ({','.join(['?']*len(allowed))})", vals
            )
            conn.commit()
            return cursor.lastrowid

    def update_domain(self, did, **fields):
        allowed = ["root_domain", "region", "service_name", "domain_name", "domain_type",
                   "env", "cert_progress", "cert_expiry", "notes"]
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates: return False
        set_clause = ", ".join(f"{k}=?" for k in updates)
        with get_conn() as conn:
            cursor = conn.execute(
                f"UPDATE domains SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                list(updates.values()) + [did]
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_domain(self, did):
        with get_conn() as conn:
            cursor = conn.execute("DELETE FROM domains WHERE id=?", (did,))
            conn.commit()
            return cursor.rowcount > 0

    def get_domain_types(self, root_domain=""):
        with get_conn() as conn:
            if root_domain:
                rows = conn.execute(
                    "SELECT DISTINCT domain_type FROM domains WHERE root_domain=? ORDER BY domain_type",
                    (root_domain,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT DISTINCT domain_type FROM domains ORDER BY domain_type"
                ).fetchall()
            return [r["domain_type"] for r in rows if r["domain_type"]]

    def get_domain_envs(self, root_domain=""):
        with get_conn() as conn:
            if root_domain:
                rows = conn.execute(
                    "SELECT DISTINCT env FROM domains WHERE root_domain=? ORDER BY env",
                    (root_domain,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT DISTINCT env FROM domains ORDER BY env"
                ).fetchall()
            return [r["env"] for r in rows if r["env"]]

    def get_root_domains(self):
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT root_domain, COUNT(*) as cnt FROM domains GROUP BY root_domain ORDER BY root_domain"
            ).fetchall()
            return [{"name": r["root_domain"], "count": r["cnt"]} for r in rows]

    def get_regions(self, root_domain=""):
        """获取区域列表（sheet 名）"""
        with get_conn() as conn:
            if root_domain:
                rows = conn.execute(
                    "SELECT DISTINCT region FROM domains WHERE root_domain=? AND region != '' ORDER BY region",
                    (root_domain,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT DISTINCT region FROM domains WHERE region != '' ORDER BY region"
                ).fetchall()
            return [r["region"] for r in rows]

    # ---- 云效创建变更单 / 运行研发流程 ----

    def _ci_query(self, table, keyword="", env="", page=1, page_size=50):
        conditions, params = [], []
        if keyword:
            conditions.append("delivery_service LIKE ?")
            params.append(f"%{keyword}%")
        if env:
            conditions.append("env = ?")
            params.append(env)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with get_conn() as conn:
            total = conn.execute(f"SELECT COUNT(*) as cnt FROM {table}{where}", params).fetchone()["cnt"]
            rows = conn.execute(
                f"SELECT * FROM {table}{where} ORDER BY id LIMIT ? OFFSET ?",
                params + [page_size, (page - 1) * page_size]
            ).fetchall()
            return [dict(r) for r in rows], total

    def get_ci_orders(self, keyword="", env="", page=1, page_size=50):
        return self._ci_query("ci_orders", keyword, env, page, page_size)

    def get_ci_devflows(self, keyword="", env="", page=1, page_size=50):
        return self._ci_query("ci_devflow", keyword, env, page, page_size)

    def _ci_get_by_id(self, table, cid):
        with get_conn() as conn:
            row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (cid,)).fetchone()
            return dict(row) if row else None

    def _ci_create(self, table, **fields):
        """创建 CI 记录 — 只插入传入的非空字段"""
        with get_conn() as conn:
            cols = [k for k, v in fields.items() if k != 'id']
            vals = [fields[k] for k in cols]
            placeholders = ",".join(["?"] * len(cols))
            cursor = conn.execute(
                f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", vals
            )
            conn.commit()
            return cursor.lastrowid

    def _ci_update(self, table, cid, **fields):
        allowed = ["delivery_service", "env", "branch", "repo_sn", "wf_sn", "stage_sn"]
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates: return False
        set_clause = ", ".join(f"{k}=?" for k in updates)
        with get_conn() as conn:
            cursor = conn.execute(
                f"UPDATE {table} SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                list(updates.values()) + [cid]
            )
            conn.commit()
            return cursor.rowcount > 0

    def _ci_delete(self, table, cid):
        with get_conn() as conn:
            cursor = conn.execute(f"DELETE FROM {table} WHERE id=?", (cid,))
            conn.commit()
            return cursor.rowcount > 0

    def _ci_envs(self, table):
        with get_conn() as conn:
            rows = conn.execute(f"SELECT DISTINCT env FROM {table} WHERE env != '' ORDER BY env").fetchall()
            return [r["env"] for r in rows]

    # ---- 用户管理 ----

    def get_users(self):
        with get_conn() as conn:
            rows = conn.execute("SELECT id, username, display_name, permissions, is_active, created_at FROM users ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def get_user_by_username(self, username):
        with get_conn() as conn:
            return conn.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,)).fetchone()

    def create_user(self, username, password, display_name="", permissions="release,credentials,domains"):
        from auth import hash_password
        with get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, display_name, permissions) VALUES (?,?,?,?)",
                (username, hash_password(password), display_name, permissions)
            )
            conn.commit()
            return cursor.lastrowid

    def update_user(self, uid, **fields):
        allowed = {"display_name", "permissions", "is_active"}
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates: return False
        if "password" in fields and fields["password"]:
            from auth import hash_password
            updates["password_hash"] = hash_password(fields["password"])
        set_clause = ", ".join(f"{k}=?" for k in updates)
        with get_conn() as conn:
            cursor = conn.execute(f"UPDATE users SET {set_clause} WHERE id=?", list(updates.values()) + [uid])
            conn.commit()
            return cursor.rowcount > 0

    def reset_password(self, uid, password):
        from auth import hash_password
        with get_conn() as conn:
            cursor = conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), uid))
            conn.commit()
            return cursor.rowcount > 0

    def delete_user(self, uid):
        with get_conn() as conn:
            cursor = conn.execute("DELETE FROM users WHERE id=? AND username != 'admin'", (uid,))
            conn.commit()
            return cursor.rowcount > 0

    def get_service_by_id(self, sid):
        """按 ID 获取单条记录"""
        with get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM service_params WHERE id = ?", (sid,)
            ).fetchone()
            return dict(row) if row else None

    def create_service(self, business_module, service_name, create_change_params="", run_devflow_params="", env="中国"):
        """新增服务"""
        with get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO service_params
                   (business_module, service_name, create_change_params, run_devflow_params, env)
                   VALUES (?, ?, ?, ?, ?)""",
                (business_module, service_name, create_change_params, run_devflow_params, env)
            )
            conn.commit()
            return cursor.lastrowid

    def update_service(self, sid, **kwargs):
        """更新服务"""
        allowed = ["business_module", "service_name", "create_change_params", "run_devflow_params", "env"]
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return False

        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [sid]

        with get_conn() as conn:
            cursor = conn.execute(
                f"UPDATE service_params SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                values
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_service(self, sid):
        """删除服务"""
        with get_conn() as conn:
            cursor = conn.execute(
                "DELETE FROM service_params WHERE id=?", (sid,)
            )
            conn.commit()
            return cursor.rowcount > 0


# 初始化数据库 + 单例
init_db()
db = Database()
