"""已批准报表的只读筛选条件发现。

此模块读取固定表的元数据和有限候选值，为页面提供动态控件配置；不生成或执行用户 SQL。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from reports import EMPLOYEE_FILTERS, FilterDefinition


@dataclass(frozen=True)
class DiscoveredFilter:
    key: str
    label: str
    kind: str
    options: tuple[str, ...] = ()


_EMPLOYEE_SCHEMA_SQL = """
SELECT COLUMN_NAME, DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
"""

_DEPARTMENT_OPTIONS_SQL = """
SELECT TOP (200) department
FROM dbo.employees
WHERE department IS NOT NULL AND LTRIM(RTRIM(department)) <> ''
GROUP BY department
ORDER BY department ASC
"""


def _filter_from_metadata(definition: FilterDefinition, data_types: dict[str, str], options: Iterable[str] = ()) -> DiscoveredFilter | None:
    data_type = data_types.get(definition.column_name.casefold())
    if definition.kind == "enum" and data_type in {"char", "varchar", "nchar", "nvarchar"}:
        return DiscoveredFilter(definition.key, definition.label, definition.kind, tuple(options))
    if definition.kind == "integer_range" and data_type in {"tinyint", "smallint", "int", "bigint"}:
        return DiscoveredFilter(definition.key, definition.label, definition.kind)
    return None


def discover_employee_filters(connection: Any) -> tuple[DiscoveredFilter, ...]:
    """通过固定、参数化的 SELECT 发现当前员工表可用筛选项。"""
    rows = connection.cursor().execute(_EMPLOYEE_SCHEMA_SQL, ["dbo", "employees"]).fetchall()
    data_types = {str(row[0]).casefold(): str(row[1]).casefold() for row in rows}
    department_rows = connection.cursor().execute(_DEPARTMENT_OPTIONS_SQL).fetchall()
    departments = tuple(str(row[0]).strip() for row in department_rows if row and row[0] is not None)

    discovered: list[DiscoveredFilter] = []
    for definition in EMPLOYEE_FILTERS:
        item = _filter_from_metadata(definition, data_types, departments if definition.key == "department" else ())
        if item:
            discovered.append(item)
    return tuple(discovered)


def discover_demo_employee_filters(dataframe: Any) -> tuple[DiscoveredFilter, ...]:
    """使用同一白名单从本地模拟数据生成筛选配置。"""
    data_types = {
        "department": "varchar" if "部门" in dataframe.columns else "",
        "age": "int" if "年龄" in dataframe.columns else "",
    }
    departments = tuple(sorted(str(value) for value in dataframe["部门"].dropna().unique())) if "部门" in dataframe.columns else ()
    return tuple(
        item
        for definition in EMPLOYEE_FILTERS
        if (item := _filter_from_metadata(definition, data_types, departments if definition.key == "department" else ()))
    )
