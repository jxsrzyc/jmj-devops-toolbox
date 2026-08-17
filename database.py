"""数据库操作模块 - 双模式支持 (SQLite / MySQL 8)"""

import os
import sqlite3
from contextlib import contextmanager

# ---------- 配置加载 ----------
def load_env(path=None):
    """读取 .env 文件（若存在）到环境变量，不覆盖已有环境变量"""
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


load_env()

DB_ENGINE = os.environ.get("DB_ENGINE", "mysql").lower()  # sqlite | mysql
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASS = os.environ.get("DB_PASS", "")
DB_NAME = os.environ.get("DB_NAME", "ops_toolbox")
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db"))


def is_mysql():
    return DB_ENGINE == "mysql"


def _clean_dt(v):
    """日期/时间字段空字符串 → None（SQLite 宽容，MySQL 严格模式不接受 ''）"""
    if v == "":
        return None
    return v


# ---------- MySQL 连接包装 ----------
class _MyConn:
    """pymysql 连接包装器：保持与 sqlite3 Connection 相同的 API
    （execute/fetchone/fetchall/commit/close/lastrowid/rowcount），
    并自动把 SQL 占位符 ? 转换为 %s。"""

    def __init__(self):
        import pymysql
        self._conn = pymysql.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASS,
            database=DB_NAME, charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
        self._cur = self._conn.cursor()

    @staticmethod
    def _fix(sql):
        return sql.replace("?", "%s")

    def execute(self, sql, params=None):
        """执行 SQL，返回 cursor（兼容 sqlite3 conn.execute() 链式 fetchone/fetchall）"""
        sql2 = self._fix(sql)
        if params is None:
            self._cur.execute(sql2)
        elif isinstance(params, (list, tuple)):
            self._cur.execute(sql2, params)
        else:
            self._cur.execute(sql2, (params,))
        return self._cur

    def executemany(self, sql, seq_of_params):
        return self._cur.executemany(self._fix(sql), seq_of_params)

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        try:
            self._cur.close()
        finally:
            self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()


@contextmanager
def get_conn():
    """获取数据库连接上下文（按 DB_ENGINE 自动切换）"""
    if is_mysql():
        conn = _MyConn()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """初始化数据库表（双模式：sqlite / mysql 自动切换方言）"""
    if is_mysql():
        _init_db_mysql()
    else:
        _init_db_sqlite()


# ---------- SQLite 建表 ----------
def _init_db_sqlite():
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_module ON service_params(business_module);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_service ON service_params(service_name);")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS service_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                env TEXT DEFAULT '',
                service_name TEXT NOT NULL,
                service_provider TEXT DEFAULT '',
                app_type TEXT DEFAULT '',
                version TEXT DEFAULT '',
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
            CREATE INDEX IF NOT EXISTS idx_cred_env ON service_credentials(env);
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_domains_root ON domains(root_domain);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_domains_domain ON domains(domain_name);")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS business_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL,
                url VARCHAR(500) NOT NULL,
                category VARCHAR(50) DEFAULT '云平台',
                description VARCHAR(200) DEFAULT '',
                color VARCHAR(7) DEFAULT '',
                sort_order INT DEFAULT 0,
                is_active INT DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bizlinks_category ON business_links(category);")
        # 兼容旧库
        link_cols = [r["name"] for r in conn.execute("PRAGMA table_info(business_links)").fetchall()]
        if "color" not in link_cols:
            conn.execute("ALTER TABLE business_links ADD COLUMN color VARCHAR(7) DEFAULT ''")
            conn.commit()
        # 业务分类顺序表（管理员可手动维护类目顺序）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bizlink_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(50) NOT NULL UNIQUE,
                sort_order INT DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # 从 business_links 自动填充首次类目
        existing_cats = conn.execute("SELECT COUNT(*) AS cnt FROM bizlink_categories").fetchone()["cnt"]
        if existing_cats == 0:
            distinct = conn.execute(
                "SELECT DISTINCT category FROM business_links WHERE category != '' ORDER BY category"
            ).fetchall()
            for i, row in enumerate(distinct):
                conn.execute(
                    "INSERT OR IGNORE INTO bizlink_categories (name, sort_order) VALUES (?, ?)",
                    (row["category"], (i + 1) * 10)
                )
            if distinct:
                conn.commit()
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ci_orders_service ON ci_orders(delivery_service);")
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
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ci_devflow_service ON ci_devflow(delivery_service);")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                display_name TEXT DEFAULT '',
                permissions TEXT DEFAULT '*',
                is_active INTEGER DEFAULT 1,
                auth_source TEXT DEFAULT 'local',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);")
        # 操作日志表（首页最近活动）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(100) NOT NULL,
                action VARCHAR(50) NOT NULL,
                module VARCHAR(50) NOT NULL DEFAULT '',
                detail VARCHAR(500) DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log(created_at);")
        conn.commit()

        from auth import hash_password
        conn.execute("""
            INSERT OR IGNORE INTO users (username, password_hash, display_name, permissions, is_active)
            VALUES ('admin', ?, '管理员', '*', 1)
        """, (hash_password("admin123"),))
        conn.commit()
        # 兼容旧库：auth_source 列不存在则补充
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        if "auth_source" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN auth_source TEXT DEFAULT 'local'")
            conn.commit()
        # 兼容旧库：service_credentials 补充 env/app_type/version 列
        cred_cols = [r["name"] for r in conn.execute("PRAGMA table_info(service_credentials)").fetchall()]
        for col, ddl in [("env", "TEXT DEFAULT ''"), ("app_type", "TEXT DEFAULT ''"), ("version", "TEXT DEFAULT ''"), ("service_provider", "TEXT DEFAULT ''")]:
            if col not in cred_cols:
                conn.execute(f"ALTER TABLE service_credentials ADD COLUMN {col} {ddl}")
                conn.commit()
        # 兼容旧库：business_links 补充 color 列（自定义图标颜色）
        link_cols = [r["name"] for r in conn.execute("PRAGMA table_info(business_links)").fetchall()]
        if "color" not in link_cols:
            conn.execute("ALTER TABLE business_links ADD COLUMN color VARCHAR(7) DEFAULT ''")
            conn.commit()


# ---------- MySQL 建表 ----------

# MySQL 不支持 CREATE INDEX IF NOT EXISTS，需先查 information_schema
def _mysql_ensure_index(conn, table, index, column_sql):
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM information_schema.statistics WHERE table_schema=%s AND table_name=%s AND index_name=%s",
        (DB_NAME, table, index)
    ).fetchone()
    if row and row["cnt"] == 0:
        conn.execute(f"CREATE INDEX {index} ON {table} ({column_sql})")


def _mysql_ensure_column(conn, table, column, ddl):
    """MySQL 兼容旧库：列不存在则 ALTER TABLE ADD COLUMN
    ddl 例：'VARCHAR(7) DEFAULT \'\''
    """
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM information_schema.columns WHERE table_schema=%s AND table_name=%s AND column_name=%s",
        (DB_NAME, table, column)
    ).fetchone()
    if row and row["cnt"] == 0:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def _init_db_mysql():
    """MySQL 8 建表：
    - TEXT 类型不能带 DEFAULT → 短文本用 VARCHAR(n) 带默认值，长文本（ssh_key/api_token/notes）用 TEXT 无默认
    - TIMESTAMP 1970-2038 限制 → 时间字段用 DATETIME
    - AUTOINCREMENT → AUTO_INCREMENT
    - INSERT OR IGNORE → INSERT IGNORE
    """
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS service_params (
                id INT AUTO_INCREMENT PRIMARY KEY,
                business_module VARCHAR(200) NOT NULL,
                service_name VARCHAR(200) NOT NULL,
                create_change_params VARCHAR(500) DEFAULT '',
                run_devflow_params VARCHAR(500) DEFAULT '',
                env VARCHAR(50) DEFAULT '中国',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        _mysql_ensure_index(conn, "service_params", "idx_module", "business_module")
        _mysql_ensure_index(conn, "service_params", "idx_service", "service_name")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS service_credentials (
                id INT AUTO_INCREMENT PRIMARY KEY,
                env VARCHAR(50) DEFAULT '',
                service_name VARCHAR(200) NOT NULL,
                service_provider VARCHAR(100) DEFAULT '',
                app_type VARCHAR(50) DEFAULT '',
                version VARCHAR(50) DEFAULT '',
                credential_type VARCHAR(50) DEFAULT '用户名密码',
                access_url VARCHAR(500) DEFAULT '',
                username VARCHAR(200) DEFAULT '',
                password VARCHAR(500) DEFAULT '',
                ssh_key TEXT,
                api_token TEXT,
                internal_url VARCHAR(500) DEFAULT '',
                internal_port INT,
                external_url VARCHAR(500) DEFAULT '',
                external_port INT,
                db_name VARCHAR(200) DEFAULT '',
                owner VARCHAR(100) DEFAULT '',
                expires_at DATE,
                status VARCHAR(20) DEFAULT '正常',
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        # 兼容旧库：service_credentials 补充 env/app_type/version 列（必须在建索引前）
        for col, ddl in [("env", "VARCHAR(50) DEFAULT ''"), ("app_type", "VARCHAR(50) DEFAULT ''"), ("version", "VARCHAR(50) DEFAULT ''"), ("service_provider", "VARCHAR(100) DEFAULT ''")]:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM information_schema.columns WHERE table_schema=%s AND table_name='service_credentials' AND column_name=%s",
                (DB_NAME, col)
            ).fetchone()
            if row and row["cnt"] == 0:
                conn.execute(f"ALTER TABLE service_credentials ADD COLUMN {col} {ddl}")
                conn.commit()
        _mysql_ensure_index(conn, "service_credentials", "idx_cred_env", "env")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS domains (
                id INT AUTO_INCREMENT PRIMARY KEY,
                root_domain VARCHAR(200) NOT NULL,
                region VARCHAR(50) DEFAULT '',
                service_name VARCHAR(200) DEFAULT '',
                domain_name VARCHAR(500) NOT NULL,
                domain_type VARCHAR(50) DEFAULT '',
                env VARCHAR(100) DEFAULT '',
                cert_progress VARCHAR(50) DEFAULT '已完成',
                cert_expiry DATETIME,
                notes TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        _mysql_ensure_index(conn, "domains", "idx_domains_root", "root_domain")
        _mysql_ensure_index(conn, "domains", "idx_domains_domain", "domain_name")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS business_links (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                url VARCHAR(500) NOT NULL,
                category VARCHAR(50) DEFAULT '云平台',
                description VARCHAR(200) DEFAULT '',
                color VARCHAR(7) DEFAULT '',
                sort_order INT DEFAULT 0,
                is_active TINYINT DEFAULT 1,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        _mysql_ensure_index(conn, "business_links", "idx_bizlinks_category", "category")
        # 兼容旧库
        _mysql_ensure_column(conn, "business_links", "color", "VARCHAR(7) DEFAULT ''")
        # 业务分类顺序表
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bizlink_categories (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(50) NOT NULL UNIQUE,
                sort_order INT DEFAULT 0,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        # 自动填充首次类目
        existing_cats = conn.execute("SELECT COUNT(*) AS cnt FROM bizlink_categories").fetchone()["cnt"]
        if existing_cats == 0:
            distinct = conn.execute(
                "SELECT DISTINCT category FROM business_links WHERE category != '' ORDER BY category"
            ).fetchall()
            for i, row in enumerate(distinct):
                conn.execute(
                    "INSERT IGNORE INTO bizlink_categories (name, sort_order) VALUES (%s, %s)",
                    (row["category"], (i + 1) * 10)
                )
            if distinct:
                conn.commit()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ci_orders (
                id INT AUTO_INCREMENT PRIMARY KEY,
                delivery_service VARCHAR(300) NOT NULL,
                env VARCHAR(50) DEFAULT '',
                branch VARCHAR(300) DEFAULT '',
                repo_sn VARCHAR(500) DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        _mysql_ensure_index(conn, "ci_orders", "idx_ci_orders_service", "delivery_service")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ci_devflow (
                id INT AUTO_INCREMENT PRIMARY KEY,
                delivery_service VARCHAR(300) NOT NULL,
                env VARCHAR(50) DEFAULT '',
                wf_sn VARCHAR(500) DEFAULT '',
                stage_sn VARCHAR(500) DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        _mysql_ensure_index(conn, "ci_devflow", "idx_ci_devflow_service", "delivery_service")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(100) NOT NULL UNIQUE,
                password_hash VARCHAR(128) NOT NULL,
                display_name VARCHAR(100) DEFAULT '',
                permissions VARCHAR(200) DEFAULT '*',
                is_active TINYINT DEFAULT 1,
                auth_source VARCHAR(20) DEFAULT 'local',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        _mysql_ensure_index(conn, "users", "idx_users_username", "username")
        # 操作日志表（首页最近活动）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS activity_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                username VARCHAR(100) NOT NULL,
                action VARCHAR(50) NOT NULL,
                module VARCHAR(50) NOT NULL DEFAULT '',
                detail VARCHAR(500) DEFAULT '',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)
        _mysql_ensure_index(conn, "activity_log", "idx_activity_created", "created_at")
        conn.commit()

        # 默认 admin 账号
        from auth import hash_password
        conn.execute("""
            INSERT IGNORE INTO users (username, password_hash, display_name, permissions, is_active)
            VALUES ('admin', %s, '管理员', '*', 1)
        """, (hash_password("admin123"),))
        conn.commit()
        # 兼容旧库：auth_source 列不存在则补充
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM information_schema.columns WHERE table_schema=%s AND table_name='users' AND column_name='auth_source'",
            (DB_NAME,)
        ).fetchone()
        if row and row["cnt"] == 0:
            conn.execute("ALTER TABLE users ADD COLUMN auth_source VARCHAR(20) DEFAULT 'local'")
            conn.commit()
        # 兼容旧库：service_credentials 补充 env/app_type/version 列
        for col, ddl in [("env", "VARCHAR(50) DEFAULT ''"), ("app_type", "VARCHAR(50) DEFAULT ''"), ("version", "VARCHAR(50) DEFAULT ''")]:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM information_schema.columns WHERE table_schema=%s AND table_name='service_credentials' AND column_name=%s",
                (DB_NAME, col)
            ).fetchone()
            if row and row["cnt"] == 0:
                conn.execute(f"ALTER TABLE service_credentials ADD COLUMN {col} {ddl}")
                conn.commit()


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

    def get_credentials(self, env="", name="", keyword="", type="", status="", page=1, page_size=20):
        """查询凭证列表（name: 业务名称模糊；keyword: 地址/账号/备注等）"""
        conditions, params = [], []
        if env:
            conditions.append("env = ?")
            params.append(env)
        if name:
            conditions.append("service_name LIKE ?")
            params.append(f"%{name}%")
        if keyword:
            conditions.append("(username LIKE ? OR notes LIKE ? OR access_url LIKE ? OR internal_url LIKE ? OR external_url LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw, kw, kw])
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
        allowed = ["env", "service_name", "service_provider", "app_type", "version", "credential_type", "access_url",
                   "username", "password", "ssh_key", "api_token", "internal_url", "internal_port",
                   "external_url", "external_port", "db_name", "owner", "expires_at", "status", "notes"]
        cols = ["env", "service_name"]
        vals = [fields.get("env", ""), fields.get("service_name", "")]
        for f in allowed[2:]:
            cols.append(f)
            vals.append(_clean_dt(fields.get(f, "")))

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
        allowed = ["env", "service_name", "service_provider", "app_type", "version", "credential_type", "access_url",
                   "username", "password", "ssh_key", "api_token", "internal_url", "internal_port",
                   "external_url", "external_port", "db_name", "owner", "expires_at", "status", "notes"]
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return False
        updates = {k: _clean_dt(v) for k, v in updates.items()}
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

    def get_credential_envs(self):
        """获取凭证环境列表（去重）"""
        with get_conn() as conn:
            rows = conn.execute("SELECT DISTINCT env FROM service_credentials WHERE env != '' ORDER BY env").fetchall()
            return [r["env"] for r in rows]

    def get_credential_service_names(self):
        """获取所有已录入的业务名称（去重：忽略大小写/首尾空格，合并拼写大小写差异）"""
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT MIN(service_name) AS name FROM service_credentials "
                "WHERE service_name != '' "
                "GROUP BY LOWER(TRIM(service_name)) "
                "ORDER BY name"
            ).fetchall()
            return [r["name"] for r in rows]

    def get_credential_providers(self):
        """获取所有已录入的服务供应商（去重，用于 datalist）"""
        with get_conn() as conn:
            rows = conn.execute("SELECT DISTINCT service_provider FROM service_credentials WHERE service_provider != '' ORDER BY service_provider").fetchall()
            return [r["service_provider"] for r in rows]

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
        vals = [_clean_dt(v) for v in (fields.get(f, "") for f in allowed)]
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
        # 日期字段空字符串 → None（MySQL 严格模式不接受 ''）
        updates = {k: _clean_dt(v) for k, v in updates.items()}
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

    # ---------- business_links（业务跳转） ----------
    def get_all_links(self, keyword="", category="", active_only=True):
        conditions, params = [], []
        if active_only:
            conditions.append("is_active = 1")
        if keyword:
            conditions.append("(name LIKE ? OR description LIKE ? OR url LIKE ?)")
            params += [f"%{keyword}%", f"%{keyword}%", f"%{keyword}%"]
        if category:
            conditions.append("category = ?")
            params.append(category)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM business_links{where} ORDER BY sort_order, id", params
            ).fetchall()
            return [dict(r) for r in rows]

    def get_link_categories(self):
        """按管理员配置的 sort_order 返回所有已用分类（如无配置则按字典序）"""
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT name FROM bizlink_categories WHERE name IN "
                "(SELECT DISTINCT category FROM business_links WHERE category != '') "
                "ORDER BY sort_order, name"
            ).fetchall()
            result = [r["name"] for r in rows if r["name"]]
            # 兜底：若 bizlink_categories 为空（极少见），退回到 dictinct
            if not result:
                rows = conn.execute(
                    "SELECT DISTINCT category FROM business_links WHERE category != '' ORDER BY category"
                ).fetchall()
                result = [r["category"] for r in rows if r["category"]]
            return result

    def ensure_category(self, name):
        """新增链接时自动登记分类（不覆盖已存在的 sort_order）"""
        if not name:
            return
        with get_conn() as conn:
            row = conn.execute("SELECT id FROM bizlink_categories WHERE name=?", (name,)).fetchone()
            if row:
                return  # 已存在 → 不动
            # 新分类：追加到末尾（MAX(sort_order) + 10）
            max_row = conn.execute("SELECT COALESCE(MAX(sort_order), 0) AS m FROM bizlink_categories").fetchone()
            max_sort = int(max_row["m"]) if max_row else 0
            conn.execute(
                "INSERT INTO bizlink_categories (name, sort_order) VALUES (%s, %s)" if False
                else "INSERT INTO bizlink_categories (name, sort_order) VALUES (?, ?)",
                (name, max_sort + 10)
            )
            conn.commit()

    def get_category_link_count(self, name):
        """获取某分类下的链接数量"""
        with get_conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM business_links WHERE category = ?", (name,)
            ).fetchone()
            return int(row["cnt"]) if row else 0

    def delete_category(self, name):
        """删除分类：该分类下链接的 category 置空（变为未分类），并删除分类行。
        返回受影响链接数"""
        if not name:
            return 0
        with get_conn() as conn:
            cnt_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM business_links WHERE category = ?", (name,)
            ).fetchone()
            cnt = int(cnt_row["cnt"]) if cnt_row else 0
            conn.execute(
                "UPDATE business_links SET category = '' WHERE category = ?", (name,)
            )
            conn.execute("DELETE FROM bizlink_categories WHERE name = ?", (name,))
            conn.commit()
        return cnt

    # ---------- activity_log（操作日志） ----------
    def count_rows(self, table):
        """通用计数（首页统计卡片）"""
        try:
            with get_conn() as conn:
                row = conn.execute(f"SELECT COUNT(*) AS cnt FROM {table}").fetchone()
                return int(row["cnt"]) if row else 0
        except Exception:
            return 0

    def add_activity(self, username, action, module="", detail=""):
        """记录一条操作日志（首页最近活动）"""
        try:
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO activity_log (username, action, module, detail) VALUES (?, ?, ?, ?)",
                    (username[:100], action[:50], module[:50], detail[:500])
                )
                # 只保留最近 200 条（外层再包一层 SELECT，兼容 MySQL 1093 同表更新限制）
                conn.execute(
                    "DELETE FROM activity_log WHERE id NOT IN "
                    "(SELECT id FROM (SELECT id FROM activity_log ORDER BY id DESC LIMIT 200) keep)"
                )
                conn.commit()
        except Exception as e:
            print(f"[activity_log] 写入失败: {e}")

    def get_recent_activities(self, limit=8):
        """最近操作日志"""
        with get_conn() as conn:
            rows = conn.execute(
                "SELECT username, action, module, detail, created_at FROM activity_log "
                "ORDER BY id DESC LIMIT ?",
                (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def reorder_categories(self, items):
        """批量更新分类顺序 items = [{'name': str, 'sort_order': int}, ...]"""
        with get_conn() as conn:
            for item in items:
                conn.execute(
                    "UPDATE bizlink_categories SET sort_order=? WHERE name=?",
                    (int(item["sort_order"]), str(item["name"]))
                )
            conn.commit()
        return True

    def get_link_by_id(self, lid):
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM business_links WHERE id=?", (lid,)).fetchone()
            return dict(row) if row else None

    def create_link(self, **fields):
        allowed = ["name", "url", "category", "description", "color", "sort_order", "is_active"]
        vals = [fields.get(f, "") for f in allowed]
        # 类型加固：is_active 默认 1，sort_order 默认 0（注意不能用 or 判断，0 是 falsy）
        for f in ("is_active", "sort_order"):
            idx = allowed.index(f)
            if vals[idx] is None or vals[idx] == "":
                vals[idx] = 1 if f == "is_active" else 0
            else:
                vals[idx] = int(vals[idx])
        with get_conn() as conn:
            cursor = conn.execute(
                f"INSERT INTO business_links ({','.join(allowed)}) VALUES ({','.join(['?']*len(allowed))})",
                vals
            )
            conn.commit()
            # 自动登记分类
            cat = vals[allowed.index("category")]
            if cat:
                self.ensure_category(cat)
            return cursor.lastrowid

    def update_link(self, lid, **fields):
        allowed = ["name", "url", "category", "description", "color", "sort_order", "is_active"]
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates: return False
        # 类型加固（不能用 or 判断，0 是 falsy）
        for k in list(updates):
            if k == "is_active":
                updates[k] = 1 if updates[k] is None or updates[k] == "" else int(updates[k])
            elif k == "sort_order":
                updates[k] = 0 if updates[k] is None or updates[k] == "" else int(updates[k])
        set_clause = ", ".join(f"{k}=?" for k in updates)
        with get_conn() as conn:
            cursor = conn.execute(
                f"UPDATE business_links SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                list(updates.values()) + [lid]
            )
            conn.commit()
            # 编辑后登记新分类（如果有的话）
            new_cat = updates.get("category")
            if new_cat:
                self.ensure_category(new_cat)
            return cursor.rowcount > 0

    def reorder_links(self, items):
        """批量更新排序：items = [{'id': int, 'sort_order': int}, ...]"""
        with get_conn() as conn:
            for item in items:
                conn.execute(
                    "UPDATE business_links SET sort_order=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                    (int(item["sort_order"]), int(item["id"]))
                )
            conn.commit()
        return True

    def delete_link(self, lid):
        with get_conn() as conn:
            cursor = conn.execute("DELETE FROM business_links WHERE id=?", (lid,))
            conn.commit()
            return cursor.rowcount > 0

    def upsert_link_by_name(self, name, **fields):
        """按 name 幂等创建/更新（预置站点导入用）"""
        with get_conn() as conn:
            row = conn.execute("SELECT id FROM business_links WHERE name=?", (name,)).fetchone()
            if row:
                allowed = ["url", "category", "description", "color", "sort_order", "is_active"]
                updates = {k: v for k, v in fields.items() if k in allowed}
                if updates:
                    set_clause = ", ".join(f"{k}=?" for k in updates)
                    conn.execute(
                        f"UPDATE business_links SET {set_clause}, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                        list(updates.values()) + [row["id"]]
                    )
                conn.commit()
                if updates.get("category"):
                    self.ensure_category(updates["category"])
                return row["id"]
            vals = {k: fields.get(k, "") for k in ["url", "category", "description", "color", "sort_order", "is_active"]}
            # 缺省值：is_active 默认 1，sort_order 默认 0（不能用 or 判断，0 是 falsy）
            vals["is_active"] = 1 if vals.get("is_active") is None or str(vals.get("is_active", "")) == "" else int(vals["is_active"])
            vals["sort_order"] = 0 if vals.get("sort_order") is None or str(vals.get("sort_order", "")) == "" else int(vals["sort_order"])
            vals["name"] = name
            cursor = conn.execute(
                "INSERT INTO business_links (name,url,category,description,color,sort_order,is_active) "
                "VALUES (?,?,?,?,?,?,?)",
                [vals["name"], vals["url"], vals["category"], vals["description"], vals.get("color", ""), vals["sort_order"], vals["is_active"]]
            )
            conn.commit()
            if vals["category"]:
                self.ensure_category(vals["category"])
            return cursor.lastrowid

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

    def _ci_delete_all(self, table):
        """清空整张 CI 表（导入前使用）"""
        with get_conn() as conn:
            conn.execute(f"DELETE FROM {table}")
            conn.commit()

    def _ci_envs(self, table):
        with get_conn() as conn:
            rows = conn.execute(f"SELECT DISTINCT env FROM {table} WHERE env != '' ORDER BY env").fetchall()
            return [r["env"] for r in rows]

    # ---- 用户管理 ----

    def get_users(self):
        with get_conn() as conn:
            rows = conn.execute("SELECT id, username, display_name, permissions, is_active, auth_source, created_at FROM users ORDER BY id").fetchall()
            return [dict(r) for r in rows]

    def get_user_by_username(self, username):
        with get_conn() as conn:
            return conn.execute("SELECT * FROM users WHERE username=? AND is_active=1", (username,)).fetchone()

    def create_user(self, username, password, display_name="", permissions="release,credentials,domains", auth_source="local"):
        from auth import hash_password
        with get_conn() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, display_name, permissions, auth_source) VALUES (?,?,?,?,?)",
                (username, hash_password(password), display_name, permissions, auth_source)
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

    # ---- 批量操作（导入/导出辅助） ----

    def count_services(self):
        """统计 service_params 总条数"""
        with get_conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM service_params").fetchone()
            return row["cnt"]

    def delete_all_services(self):
        """清空 service_params（seed.py 导入前使用）"""
        with get_conn() as conn:
            conn.execute("DELETE FROM service_params")
            conn.commit()

    def delete_domains_by_root(self, root_domain):
        """按 root_domain 清空域名数据（导入前使用）"""
        with get_conn() as conn:
            conn.execute("DELETE FROM domains WHERE root_domain=?", (root_domain,))
            conn.commit()

    def get_all_domains_for_export(self, root_domain="", keyword="", env="", dtype="", region=""):
        """查询全部符合条件的域名（不分页，供导出用）"""
        conditions, params = [], []
        if root_domain:
            conditions.append("root_domain = ?"); params.append(root_domain)
        if region:
            conditions.append("region = ?"); params.append(region)
        if keyword:
            conditions.append("(domain_name LIKE ? OR service_name LIKE ?)")
            kw = f"%{keyword}%"; params.extend([kw, kw])
        if env:
            conditions.append("env = ?"); params.append(env)
        if dtype:
            conditions.append("domain_type = ?"); params.append(dtype)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with get_conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM domains{where} ORDER BY region, domain_type, id", params
            ).fetchall()
            return [dict(r) for r in rows]


# 初始化数据库 + 单例
init_db()
db = Database()
