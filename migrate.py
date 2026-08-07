#!/usr/bin/env python3
"""数据迁移脚本 - SQLite (data.db) → MySQL (ops_toolbox)

用法:
    python3 migrate.py            # 正常迁移
    python3 migrate.py --dry-run  # 只读检查，不写入 MySQL

安全说明:
    - 迁移前自动备份 data.db → data.db.bak
    - 迁移时保留自增 id
    - 逐表迁移 + 行数校验
"""

import os
import sys
import shutil
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 加载 .env 配置（与 database.py 共用）
def load_env(path=None):
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

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.db")

TABLES = [
    "service_params",
    "service_credentials",
    "domains",
    "ci_orders",
    "ci_devflow",
    "users",
]


def get_sqlite_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_mysql_conn():
    import pymysql
    conn = pymysql.connect(
        host=os.environ.get("DB_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASS", ""),
        database=os.environ.get("DB_NAME", "ops_toolbox"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )
    return conn


def table_exists(mysql_conn, table):
    with mysql_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM information_schema.tables WHERE table_schema=%s AND table_name=%s",
            (os.environ.get("DB_NAME", "ops_toolbox"), table),
        )
        return cur.fetchone()["cnt"] > 0


def migrate_table(sq_conn, my_conn, table, dry_run=False):
    """迁移单张表，返回 (源行数, 目标行数)"""
    sq_rows = sq_conn.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
    if not sq_rows:
        print(f"  [{table}] 源表为空，跳过")
        return 0, 0

    cols = list(sq_rows[0].keys())
    col_str = ",".join(cols)
    placeholders = ",".join(["%s"] * len(cols))

    if dry_run:
        print(f"  [{table}] dry-run: {len(sq_rows)} 行待迁移")
        return len(sq_rows), 0

    if table_exists(my_conn, table):
        with my_conn.cursor() as cur:
            cur.execute(f"TRUNCATE TABLE {table}")
        print(f"  [{table}] 目标表已存在，先清空")

    insert_sql = f"INSERT INTO {table} ({col_str}) VALUES ({placeholders})"
    with my_conn.cursor() as cur:
        for row in sq_rows:
            cur.execute(insert_sql, tuple(row[k] for k in cols))
    my_conn.commit()

    # 校验
    with my_conn.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS cnt FROM {table}")
        target_cnt = cur.fetchone()["cnt"]

    print(f"  [{table}] 迁移完成: 源 {len(sq_rows)} 行 → 目标 {target_cnt} 行 {'✓' if len(sq_rows) == target_cnt else '⚠️ 不一致!'}")
    return len(sq_rows), target_cnt


def main():
    if not os.path.exists(DB_PATH):
        print(f"❌ 找不到 SQLite 文件: {DB_PATH}")
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv

    print("=" * 50)
    print("SQLite → MySQL 数据迁移")
    print(f"  源: {DB_PATH}")
    print(f"  目标: {os.environ.get('DB_HOST','127.0.0.1')}:{os.environ.get('DB_PORT','3306')}/{os.environ.get('DB_NAME','ops_toolbox')}")
    print(f"  模式: {'dry-run（只读检查）' if dry_run else '正常迁移'}")
    print("=" * 50)

    # 备份（非 dry-run 才备份）
    if not dry_run:
        bak = f"{DB_PATH}.bak"
        shutil.copy2(DB_PATH, bak)
        print(f"✅ 已备份: {bak}")

    sq_conn = get_sqlite_conn()
    my_conn = get_mysql_conn() if not dry_run else None
    try:
        for table in TABLES:
            print(f"\n--- 迁移 {table} ---")
            migrate_table(sq_conn, my_conn, table, dry_run=dry_run)

        print("\n" + "=" * 50)
        if dry_run:
            print("dry-run 完成（未写入任何数据）")
        else:
            print("✅ 全部迁移完成！")
            print("   请启动应用验证功能，确认无误后再考虑清理 data.db.bak")
        print("=" * 50)
    finally:
        sq_conn.close()
        if my_conn:
            my_conn.close()


if __name__ == "__main__":
    main()
