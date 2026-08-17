# -*- coding: utf-8 -*-
"""内置节假日数据（兜底用，timor-api 不可达时降级到这里）。
数据来源：国务院办公厅《关于2026年部分节假日安排的通知》
结构对齐 timor-api：{MM-DD: {date, name, isOffDay, wage}}
"""

BUILTIN_HOLIDAYS = {
    "2026": {
        # ---- 元旦（1/1 周四 - 1/3 周六，1/4 周日上班）----
        "01-01": {"date": "2026-01-01", "name": "元旦", "isOffDay": True, "wage": 3},
        "01-02": {"date": "2026-01-02", "name": "元旦", "isOffDay": True, "wage": 2},
        "01-03": {"date": "2026-01-03", "name": "元旦", "isOffDay": True, "wage": 2},
        "01-04": {"date": "2026-01-04", "name": "元旦", "isOffDay": False, "wage": 0},
        # ---- 春节（2/15 周日 - 2/23 周一，2/14 周六、2/28 周六上班）----
        "02-14": {"date": "2026-02-14", "name": "春节", "isOffDay": False, "wage": 0},
        "02-15": {"date": "2026-02-15", "name": "春节", "isOffDay": True, "wage": 3},
        "02-16": {"date": "2026-02-16", "name": "春节", "isOffDay": True, "wage": 3},
        "02-17": {"date": "2026-02-17", "name": "春节", "isOffDay": True, "wage": 3},
        "02-18": {"date": "2026-02-18", "name": "春节", "isOffDay": True, "wage": 3},
        "02-19": {"date": "2026-02-19", "name": "春节", "isOffDay": True, "wage": 2},
        "02-20": {"date": "2026-02-20", "name": "春节", "isOffDay": True, "wage": 2},
        "02-21": {"date": "2026-02-21", "name": "春节", "isOffDay": True, "wage": 2},
        "02-22": {"date": "2026-02-22", "name": "春节", "isOffDay": True, "wage": 2},
        "02-23": {"date": "2026-02-23", "name": "春节", "isOffDay": True, "wage": 2},
        "02-28": {"date": "2026-02-28", "name": "春节", "isOffDay": False, "wage": 0},
        # ---- 清明节（4/4 周六 - 4/6 周一，不调休）----
        "04-04": {"date": "2026-04-04", "name": "清明节", "isOffDay": True, "wage": 2},
        "04-05": {"date": "2026-04-05", "name": "清明节", "isOffDay": True, "wage": 2},
        "04-06": {"date": "2026-04-06", "name": "清明节", "isOffDay": True, "wage": 2},
        # ---- 劳动节（5/1 周五 - 5/5 周二，5/9 周六上班）----
        "05-01": {"date": "2026-05-01", "name": "劳动节", "isOffDay": True, "wage": 3},
        "05-02": {"date": "2026-05-02", "name": "劳动节", "isOffDay": True, "wage": 2},
        "05-03": {"date": "2026-05-03", "name": "劳动节", "isOffDay": True, "wage": 2},
        "05-04": {"date": "2026-05-04", "name": "劳动节", "isOffDay": True, "wage": 2},
        "05-05": {"date": "2026-05-05", "name": "劳动节", "isOffDay": True, "wage": 2},
        "05-09": {"date": "2026-05-09", "name": "劳动节", "isOffDay": False, "wage": 0},
        # ---- 端午节（6/19 周五 - 6/21 周日，不调休）----
        "06-19": {"date": "2026-06-19", "name": "端午节", "isOffDay": True, "wage": 3},
        "06-20": {"date": "2026-06-20", "name": "端午节", "isOffDay": True, "wage": 2},
        "06-21": {"date": "2026-06-21", "name": "端午节", "isOffDay": True, "wage": 2},
        # ---- 中秋节（9/25 周五 - 9/27 周日，不调休）----
        "09-25": {"date": "2026-09-25", "name": "中秋节", "isOffDay": True, "wage": 3},
        "09-26": {"date": "2026-09-26", "name": "中秋节", "isOffDay": True, "wage": 2},
        "09-27": {"date": "2026-09-27", "name": "中秋节", "isOffDay": True, "wage": 2},
        # ---- 国庆节（10/1 周四 - 10/7 周三，9/20 周日、10/10 周六上班）----
        "09-20": {"date": "2026-09-20", "name": "国庆节", "isOffDay": False, "wage": 0},
        "10-01": {"date": "2026-10-01", "name": "国庆节", "isOffDay": True, "wage": 3},
        "10-02": {"date": "2026-10-02", "name": "国庆节", "isOffDay": True, "wage": 3},
        "10-03": {"date": "2026-10-03", "name": "国庆节", "isOffDay": True, "wage": 3},
        "10-04": {"date": "2026-10-04", "name": "国庆节", "isOffDay": True, "wage": 2},
        "10-05": {"date": "2026-10-05", "name": "国庆节", "isOffDay": True, "wage": 2},
        "10-06": {"date": "2026-10-06", "name": "国庆节", "isOffDay": True, "wage": 2},
        "10-07": {"date": "2026-10-07", "name": "国庆节", "isOffDay": True, "wage": 2},
        "10-10": {"date": "2026-10-10", "name": "国庆节", "isOffDay": False, "wage": 0},
    }
}


def get_builtin_holidays(year):
    """返回 {MM-DD: {name, isOffDay}}，未知年份返回空 dict"""
    data = BUILTIN_HOLIDAYS.get(str(year), {})
    return {k: {"name": v.get("name", ""), "isOffDay": bool(v.get("isOffDay"))}
            for k, v in data.items()}
