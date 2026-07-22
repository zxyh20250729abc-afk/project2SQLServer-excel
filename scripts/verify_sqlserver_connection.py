"""真实 SQL Server 接入前的只读连通性与权限核验工具。

本脚本只执行 SELECT；不创建对象、不写入审计表、不修改源数据库任何数据。
"""

from __future__ import annotations

from pathlib import Path
import sys
import tomllib

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from database import readonly_connection  # noqa: E402
from reports import build_params, get_report  # noqa: E402


def main() -> None:
    config_path = PROJECT_ROOT / ".streamlit" / "secrets.toml"
    if not config_path.exists():
        raise SystemExit("缺少 .streamlit/secrets.toml。请先从 secrets.toml.example 复制并填写只读账号。")

    with config_path.open("rb") as config_file:
        settings = tomllib.load(config_file)
    sql_settings = settings.get("sqlserver", {})
    report = get_report("employee_list")
    params = build_params(None, None, None)

    with readonly_connection(sql_settings) as connection:
        # 仅验证连通性、当前身份和员工测试表可读性。
        identity = connection.cursor().execute("SELECT SYSTEM_USER AS login_name, DB_NAME() AS database_name").fetchone()
        row = connection.cursor().execute(report.count_sql, params).fetchone()

    print(f"连接成功：账号={identity[0]}，数据库={identity[1]}")
    print(f"员工表读取成功：匹配行数={int(row[0]) if row else 0}")
    print("核验完成：脚本未执行 INSERT、UPDATE、DELETE、DDL 或存储过程。")


if __name__ == "__main__":
    main()
