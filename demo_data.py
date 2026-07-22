"""用于 MVP 演示的本地模拟订单数据。

该模块只服务于界面和 Excel 功能验证；不会连接、写入或伪造 SQL Server 数据。
真实环境应在 secrets.toml 中将 app.mode 设置为 sqlserver。
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


DEPARTMENTS = ("销售部", "市场部", "运营部", "客服部")
STATUSES = ("待处理", "已完成", "已取消")
CUSTOMERS = ("上海启明科技", "北京星河商贸", "深圳远航物流", "杭州云川信息", "成都锦程服务")


def load_demo_orders() -> pd.DataFrame:
    """返回可重复生成的 180 条模拟订单，便于稳定演示与测试。"""
    start = date.today() - timedelta(days=89)
    rows: list[dict[str, object]] = []
    for index in range(180):
        rows.append(
            {
                "订单编号": f"DEMO-{20260001 + index}",
                "客户名称": CUSTOMERS[index % len(CUSTOMERS)],
                "订单日期": start + timedelta(days=index // 2),
                "部门": DEPARTMENTS[index % len(DEPARTMENTS)],
                "状态": STATUSES[index % len(STATUSES)],
                "金额": round(980 + (index * 137.5) % 16000, 2),
            }
        )
    return pd.DataFrame(rows)


def filter_demo_orders(
    dataframe: pd.DataFrame,
    *,
    start_date: date,
    end_date: date,
    department: str | None,
    status: str | None,
) -> pd.DataFrame:
    """按和真实报表一致的条件筛选模拟数据。"""
    result = dataframe.loc[
        (dataframe["订单日期"] >= start_date) & (dataframe["订单日期"] <= end_date)
    ]
    if department:
        result = result.loc[result["部门"] == department]
    if status:
        result = result.loc[result["状态"] == status]
    return result.sort_values(["订单日期", "订单编号"], ascending=[False, False]).reset_index(drop=True)
