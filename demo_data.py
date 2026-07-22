"""用于 MVP 演示的本地模拟员工数据。

该模块只服务于界面和 Excel 功能验证；不会连接、写入或伪造 SQL Server 数据。
真实环境应在 secrets.toml 中将 app.mode 设置为 sqlserver。
"""

from __future__ import annotations

import pandas as pd


DEPARTMENTS = ("销售部", "市场部", "运营部", "客服部")
LAST_NAMES = ("张", "王", "李", "赵", "陈", "刘")
FIRST_NAMES = ("伟", "娜", "敏", "磊", "静", "强")


def load_demo_employees() -> pd.DataFrame:
    """返回可重复生成的 180 条模拟员工数据，便于稳定演示与测试。"""
    rows: list[dict[str, object]] = []
    for index in range(180):
        rows.append(
            {
                "人员编号": index + 1,
                "姓": LAST_NAMES[index % len(LAST_NAMES)],
                "名": FIRST_NAMES[index % len(FIRST_NAMES)],
                "年龄": 20 + (index % 41),
                "部门": DEPARTMENTS[index % len(DEPARTMENTS)],
                "薪资": round(6800 + (index * 137.5) % 22000, 2),
            }
        )
    return pd.DataFrame(rows)


def filter_demo_employees(
    dataframe: pd.DataFrame,
    *,
    department: str | None,
    min_age: int | None,
    max_age: int | None,
) -> pd.DataFrame:
    """按和真实报表一致的条件筛选模拟数据。"""
    result = dataframe
    if department:
        result = result.loc[result["部门"] == department]
    if min_age is not None:
        result = result.loc[result["年龄"] >= min_age]
    if max_age is not None:
        result = result.loc[result["年龄"] <= max_age]
    return result.sort_values("人员编号", ascending=True).reset_index(drop=True)
