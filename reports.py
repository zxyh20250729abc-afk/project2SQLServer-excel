"""受控报表定义。

仅允许维护者在此文件调整 SQL、字段和可选条件。页面不会接受用户编写的 SQL，
以避免 SQL 注入、越权查询和不可预测的数据库负载。
"""

from dataclasses import dataclass
from datetime import date
import re
from typing import Any


@dataclass(frozen=True)
class ReportDefinition:
    key: str
    name: str
    description: str
    source_note: str
    data_sql: str
    preview_sql: str
    count_sql: str


# 对接时：将 dbo.vw_report_export 和字段名替换为 DBA 批准的只读视图/字段。
# 日期使用 [start_date, end_date) 半开区间，避免结束日漏数。
_BASE_WHERE = """
WHERE order_date >= ?
  AND order_date < ?
  AND (? IS NULL OR department_name = ?)
  AND (? IS NULL OR order_status = ?)
"""

_SELECT_COLUMNS = """
SELECT
    order_no        AS [订单编号],
    customer_name   AS [客户名称],
    order_date      AS [订单日期],
    department_name AS [部门],
    order_status    AS [状态],
    amount          AS [金额]
FROM dbo.vw_report_export
"""

ORDER_DETAIL_REPORT = ReportDefinition(
    key="order_detail",
    name="订单明细",
    description="按日期、部门和状态导出订单明细。",
    source_note="数据源：dbo.vw_report_export（上线前替换为已批准的数据视图）。",
    data_sql=_SELECT_COLUMNS + _BASE_WHERE + "ORDER BY order_date DESC, order_no DESC",
    preview_sql="SELECT TOP (100) * FROM (" + _SELECT_COLUMNS + _BASE_WHERE + ") AS report_preview ORDER BY [订单日期] DESC, [订单编号] DESC",
    count_sql="SELECT COUNT_BIG(1) AS row_count FROM dbo.vw_report_export " + _BASE_WHERE,
)

REPORTS: dict[str, ReportDefinition] = {ORDER_DETAIL_REPORT.key: ORDER_DETAIL_REPORT}

# SQL Server 数据访问的第二道代码防线：本应用的远程查询只能是单条 SELECT。
# 这不是数据库权限的替代品；最终写保护必须由只读数据库账号实现。
_BLOCKED_SQL_TOKENS = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|TRUNCATE|ALTER|DROP|CREATE|EXEC|EXECUTE|"
    r"GRANT|REVOKE|DENY|BACKUP|RESTORE|DBCC)\b",
    re.IGNORECASE,
)


def validate_read_only_sql(sql: str) -> None:
    """拒绝非 SELECT 或含写入/管理关键词的 SQL。"""
    normalized = " ".join(sql.split())
    if not normalized.upper().startswith("SELECT "):
        raise ValueError("只允许执行 SELECT 查询。")
    if ";" in normalized or "--" in normalized or "/*" in normalized:
        raise ValueError("查询模板不允许包含多语句或 SQL 注释。")
    if _BLOCKED_SQL_TOKENS.search(normalized):
        raise ValueError("查询模板包含不允许的写入或管理操作。")


def validate_report_read_only(report: ReportDefinition) -> None:
    """确保报表的计数、预览和导出 SQL 都符合只读限制。"""
    for sql in (report.data_sql, report.preview_sql, report.count_sql):
        validate_read_only_sql(sql)


def get_report(report_key: str) -> ReportDefinition:
    """返回批准的报表定义；未知报表不得执行。"""
    try:
        report = REPORTS[report_key]
        validate_report_read_only(report)
        return report
    except KeyError as exc:
        raise ValueError("未授权的报表类型。") from exc


def build_params(
    start_date: date,
    end_date_exclusive: date,
    department: str | None,
    status: str | None,
) -> list[Any]:
    """按固定 SQL 中的 ? 占位符顺序绑定参数，绝不拼接用户输入。"""
    return [
        start_date,
        end_date_exclusive,
        department,
        department,
        status,
        status,
    ]
