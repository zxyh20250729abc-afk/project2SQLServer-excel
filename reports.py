"""受控报表定义。

仅允许维护者在此文件调整 SQL、字段和可选条件。页面不会接受用户编写的 SQL，
以避免 SQL 注入、越权查询和不可预测的数据库负载。
"""

from dataclasses import dataclass
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


# 当前连接的是测试库中的 dbo.employees。
# 生产环境应由 DBA 替换为已批准、只包含必要字段的只读视图。
_EMPLOYEE_WHERE = """
WHERE (? IS NULL OR department = ?)
  AND (? IS NULL OR age >= ?)
  AND (? IS NULL OR age <= ?)
"""

_EMPLOYEE_COLUMNS = """
SELECT
    personid  AS [人员编号],
    lastname  AS [姓],
    firstname AS [名],
    age       AS [年龄],
    department AS [部门],
    salary    AS [薪资]
FROM dbo.employees
"""

EMPLOYEE_REPORT = ReportDefinition(
    key="employee_list",
    name="员工信息",
    description="按部门和年龄范围导出员工信息。",
    source_note="数据源：dbo.employees（当前测试库；生产环境应替换为 DBA 批准的只读视图）。",
    data_sql=_EMPLOYEE_COLUMNS + _EMPLOYEE_WHERE + "ORDER BY personid ASC",
    preview_sql="SELECT TOP (100) * FROM (" + _EMPLOYEE_COLUMNS + _EMPLOYEE_WHERE + ") AS report_preview ORDER BY [人员编号] ASC",
    count_sql="SELECT COUNT_BIG(1) AS row_count FROM dbo.employees " + _EMPLOYEE_WHERE,
)

REPORTS: dict[str, ReportDefinition] = {EMPLOYEE_REPORT.key: EMPLOYEE_REPORT}

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
    department: str | None,
    min_age: int | None,
    max_age: int | None,
) -> list[Any]:
    """按固定 SQL 中的 ? 占位符顺序绑定参数，绝不拼接用户输入。"""
    return [
        department,
        department,
        min_age,
        min_age,
        max_age,
        max_age,
    ]
