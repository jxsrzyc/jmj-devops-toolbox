#!/usr/bin/env python3
"""种子数据导入脚本 - 从 Excel 导入数据到 SQLite"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import init_db, db
import pandas as pd

EXCEL_PATH = os.path.expanduser("~/Downloads/蓝鲸云效服务发版参数列表.xlsx")


def main():
    if not os.path.exists(EXCEL_PATH):
        print(f"找不到文件: {EXCEL_PATH}")
        sys.exit(1)

    # ⚠️ 安全检查：seed.py 会清空 service_params 表，需要明确确认或 --force
    force = "--force" in sys.argv
    db_path = os.path.join(os.path.dirname(__file__), "data.db")
    if os.path.exists(db_path):
        import sqlite3
        existing = sqlite3.connect(db_path).execute("SELECT COUNT(*) FROM service_params").fetchone()[0]
        if existing > 0 and not force:
            print(f"⚠️  数据库已存在 {existing} 条 service_params 记录")
            print("seed.py 会先清空再导入。")
            print("如确认要清空并重新导入，请加 --force 参数：")
            print(f"  python3 seed.py --force")
            sys.exit(1)

    init_db()

    df = pd.read_excel(EXCEL_PATH)
    df.columns = ["business_module", "service_name", "create_change_params", "run_devflow_params", "env"]

    # 清空 service_params（幂等性）— 其他表（credentials/domains/ci_*）保留
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM service_params")
    conn.commit()
    conn.close()

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

    print(f"导入完成：{count} 条记录，{len(df['business_module'].unique())} 个业务模块")
    print("⚠️  提示：seed.py 只影响 service_params，其他表未受影响")


if __name__ == "__main__":
    main()
