"""真实 SQL Server 接入前的只读连通性与报表权限核验工具。

本脚本只执行 SELECT；不创建对象、不写入审计表、不修改源数据库任何数据。
"""

from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import sys
import tomllib
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from database import readonly_connection  # noqa: E402
from reports import ReportDefinition, available_reports, build_params, get_report  # noqa: E402


def default_filter_values(report: ReportDefinition) -> dict[str, Any]:
    """为指定预设报表提供小范围、只读的连通性核验参数。"""
    start_date = date.today().replace(day=1)
    end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    values: dict[str, Any] = {
        "department": None,
        "min_age": None,
        "max_age": None,
        "year": date.today().year,
        "start_month": date.today().month,
        "end_month": date.today().month,
        "start_date": start_date,
        "end_date": end_date,
    }
    return {definition.key: values[definition.key] for definition in report.filters} | {
        key: values[key]
        for sheet in report.sheets
        for key in sheet.parameter_keys
        if key in values
    }


def parse_arguments() -> argparse.Namespace:
    report_options = ", ".join(report.key for report in available_reports("sqlserver"))
    parser = argparse.ArgumentParser(description="核验 SQL Server 只读连接和一个预设报表的读取权限。")
    parser.add_argument(
        "--report",
        default="employee_list",
        help=f"要核验的预设报表 key，默认 employee_list。可选：{report_options}",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_arguments()
    config_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if not config_path.exists():
        raise SystemExit("缺少 .streamlit/secrets.toml。请先从 secrets.toml.example 复制并填写只读账号。")

    with config_path.open("rb") as config_file:
        settings = tomllib.load(config_file)
    sql_settings = settings.get("sqlserver", {})
    try:
        report = get_report(args.report)
    except ValueError as exc:
        raise SystemExit(f"报表不存在或未获批准：{args.report}") from exc
    filters = default_filter_values(report)

    with readonly_connection(sql_settings) as connection:
        identity = connection.cursor().execute("SELECT SYSTEM_USER AS login_name, DB_NAME() AS database_name").fetchone()
        sheet_counts: list[tuple[str, int]] = []
        for sheet in report.sheets:
            row = connection.cursor().execute(sheet.count_sql, build_params(sheet, filters)).fetchone()
            sheet_counts.append((sheet.name, int(row[0]) if row else 0))

    print(f"连接成功：账号={identity[0]}，数据库={identity[1]}")
    print(f"已核验报表：{report.name}")
    for sheet_name, row_count in sheet_counts:
        print(f"  {sheet_name}：可读取，匹配行数={row_count}")
    print("核验完成：脚本未执行 INSERT、UPDATE、DELETE、DDL 或存储过程。")


if __name__ == "__main__":
    main()
