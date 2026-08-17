"""project2SQLServer导入excel系统入口。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st

from audit import record
from database import DatabaseConnectionError, QueryExecutionError, ReadonlyAccountError, count_rows, fetch_export, fetch_preview, readonly_connection
from demo_data import filter_demo_employees, load_demo_employees
from discovery import DiscoveredFilter, discover_demo_employee_filters, discover_employee_filters
from exporter import create_filename, dataframes_to_excel
from reports import ReportDefinition, available_reports, build_params, get_report


def get_settings() -> tuple[str, dict[str, Any], dict[str, Any]]:
    """读取运行模式和配置；缺少密钥文件时安全回退到演示模式。"""
    try:
        app_settings = dict(st.secrets.get("app", {}))
        mode = str(app_settings.get("mode", "demo")).lower()
        sql_settings = dict(st.secrets.get("sqlserver", {}))
    except (FileNotFoundError, KeyError):
        return "demo", {}, {}

    if mode not in {"demo", "sqlserver"}:
        raise RuntimeError("app.mode 只能设置为 demo 或 sqlserver。")
    if mode == "sqlserver" and not sql_settings:
        raise RuntimeError("SQL Server 模式缺少数据库配置。请检查 .streamlit/secrets.toml。")
    return mode, sql_settings, app_settings


def parse_optional_age(value: str, field_name: str) -> tuple[int | None, str | None]:
    """解析可选年龄，避免将页面输入直接带入查询。"""
    value = value.strip()
    if not value:
        return None, None
    if not value.isdigit():
        return None, f"{field_name}必须是整数。"
    age = int(value)
    if not 0 <= age <= 150:
        return None, f"{field_name}应在 0 到 150 之间。"
    return age, None


def get_employee_filter_definitions(mode: str, sql_settings: dict[str, Any]) -> tuple[DiscoveredFilter, ...]:
    """仅员工测试报表使用固定的只读元数据查询发现候选部门。"""
    if mode == "demo":
        return discover_demo_employee_filters(load_demo_employees())
    with readonly_connection(sql_settings) as connection:
        return discover_employee_filters(connection)


def _default_date_range() -> tuple[date, date]:
    start_date = date.today().replace(day=1)
    end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start_date, end_date


def render_employee_filters(mode: str, sql_settings: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """渲染现有员工测试报表的部门、年龄控件。"""
    try:
        definitions = get_employee_filter_definitions(mode, sql_settings)
    except (DatabaseConnectionError, ReadonlyAccountError, QueryExecutionError) as exc:
        return None, f"无法读取已批准的筛选条件：{exc}"

    by_key = {item.key: item for item in definitions}
    if "department" not in by_key or "age" not in by_key:
        return None, "数据库表结构未包含已批准的 department 与 age 筛选字段，已停止查询。"

    col1, col2, col3 = st.columns(3)
    with col1:
        definition = by_key["department"]
        department = st.selectbox(f"{definition.label}（可选）", options=("全部", *definition.options), key="employee_department")
    with col2:
        min_age_text = st.text_input(f"最小{by_key['age'].label}（可选）", max_chars=3, key="employee_min_age")
    with col3:
        max_age_text = st.text_input(f"最大{by_key['age'].label}（可选）", max_chars=3, key="employee_max_age")

    min_age, min_error = parse_optional_age(min_age_text, "最小年龄")
    max_age, max_error = parse_optional_age(max_age_text, "最大年龄")
    if min_error or max_error:
        return None, min_error or max_error
    if min_age is not None and max_age is not None and min_age > max_age:
        return None, "最小年龄不能大于最大年龄。"
    return {
        "department": None if department == "全部" else department,
        "min_age": min_age,
        "max_age": max_age,
    }, None


def render_business_filters(report: ReportDefinition) -> tuple[dict[str, Any], str | None]:
    """根据经批准的报表参数生成日期、年度和月份控件。"""
    values: dict[str, Any] = {}
    default_start, default_end = _default_date_range()
    columns = st.columns(min(max(len(report.filters), 1), 3))

    for index, definition in enumerate(report.filters):
        with columns[index % len(columns)]:
            key = f"{report.key}_{definition.key}"
            if definition.kind == "date":
                default_value = default_start if definition.key == "start_date" else default_end
                values[definition.key] = st.date_input(definition.label, value=default_value, key=key)
            elif definition.kind == "month":
                values[definition.key] = st.selectbox(
                    definition.label,
                    options=tuple(range(int(definition.minimum or 1), int(definition.maximum or 12) + 1)),
                    key=key,
                )
            elif definition.kind == "integer":
                options = tuple(range(int(definition.minimum or 0), int(definition.maximum or 9999) + 1))
                current_year = date.today().year
                default_index = options.index(current_year) if current_year in options else 0
                values[definition.key] = st.selectbox(
                    definition.label,
                    options=options,
                    index=default_index,
                    key=key,
                )
            else:
                return values, "报表筛选条件配置错误，已停止查询。"

    if "start_month" in values and "end_month" in values and values["start_month"] > values["end_month"]:
        return values, "起始月份不能晚于结束月份。"
    if "start_date" in values and "end_date" in values and values["start_date"] >= values["end_date"]:
        return values, "结束日期必须晚于开始日期。"
    return values, None


def get_form_filters(report: ReportDefinition, mode: str, sql_settings: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if report.key == "employee_list":
        return render_employee_filters(mode, sql_settings)
    return render_business_filters(report)


def main() -> None:
    st.set_page_config(page_title="project2SQLServer导入excel系统", page_icon="📊", layout="wide")
    st.title("project2SQLServer导入excel系统")
    st.caption("预设业务统计 · SQL Server 只读访问 · Excel 导出")

    with st.expander("数据安全与权限说明", expanded=True):
        st.markdown(
            """
            - 本系统仅执行经过批准的 **SELECT 查询**，用于预览和导出 Excel。
            - 页面不提供 SQL 输入框，也不支持新增、修改、删除、建表、删表、修改表结构或执行存储过程。
            - 所有筛选条件均通过参数传递，不会拼接为可执行 SQL；系统会拒绝包含写入或管理操作的查询模板。
            - 数据库必须使用 DBA 配置的专用只读账号。检测到 `sysadmin`、`db_owner` 或 `db_datawriter` 等高权限账号时，系统会阻止查询和导出。
            - 最终的数据保护由 SQL Server 权限强制实施：应用账号仅应拥有已批准报表对象的 `SELECT` 权限。
            """
        )

    try:
        mode, sql_settings, app_settings = get_settings()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    options = available_reports(mode)
    reports_by_key = {report.key: report for report in options}
    report_key = st.selectbox("选择统计报表", options=tuple(reports_by_key), format_func=lambda key: reports_by_key[key].name)
    report = get_report(report_key)
    st.subheader(report.name)
    st.caption(report.description)
    st.caption(report.source_note)

    if mode == "demo":
        st.info("当前为模拟数据模式：仅开放员工测试报表，不会连接 SQL Server。")
    else:
        st.info("当前为 SQL Server 只读模式：仅能运行系统预设报表，不能输入或执行任意 SQL。")

    with st.form("query_form"):
        operator_id = st.text_input("姓名或工号", max_chars=100, help="仅用于导出审计。")
        filters, filter_error = get_form_filters(report, mode, sql_settings)
        submitted = st.form_submit_button("查询预览", type="primary")

    if not submitted:
        return
    if not operator_id.strip():
        st.warning("请输入姓名或工号，用于导出审计。")
        return
    if filter_error:
        st.warning(filter_error)
        return
    if filters is None:
        st.error("无法生成查询条件，已停止查询。")
        return

    audit_path = str(app_settings.get("audit_db_path", "audit.db"))

    try:
        with st.spinner("正在准备数据..."):
            export_sheets: dict[str, Any] = {}
            preview_sheets: list[tuple[str, int, Any]] = []
            if mode == "demo":
                # 演示模式仅会出现 employee_list，由固定本地数据完成完整流程验证。
                export_data = filter_demo_employees(load_demo_employees(), **filters)
                sheet_name = report.sheets[0].name
                export_sheets[sheet_name] = export_data
                preview_sheets.append((sheet_name, len(export_data), export_data.head(100)))
            else:
                with readonly_connection(sql_settings) as connection:
                    max_export_rows = int(app_settings.get("max_export_rows", 1_048_576))
                    total_rows = 0
                    sheet_counts: list[tuple[Any, int]] = []
                    for sheet in report.sheets:
                        params = build_params(sheet, filters)
                        row_count = count_rows(connection, sheet, params)
                        total_rows += row_count
                        if total_rows > max_export_rows:
                            raise QueryExecutionError(f"查询结果超过 {max_export_rows:,} 行，请缩小筛选条件。")
                        sheet_counts.append((sheet, row_count))

                    for sheet, row_count in sheet_counts:
                        params = build_params(sheet, filters)
                        preview = fetch_preview(connection, sheet, params)
                        export_data = fetch_export(connection, sheet, params)
                        export_sheets[sheet.name] = export_data
                        preview_sheets.append((sheet.name, row_count, preview))

        total_rows = sum(row_count for _, row_count, _ in preview_sheets)
        sheet_summary = "；".join(f"{name} {row_count:,} 行" for name, row_count, _ in preview_sheets)
        st.success(f"查询完成，共 {total_rows:,} 行。{sheet_summary}")
        for sheet_name, row_count, preview in preview_sheets:
            st.markdown(f"##### {sheet_name}")
            if row_count:
                st.caption(f"展示前 {len(preview):,} 行")
                st.dataframe(preview, width="stretch", hide_index=True)
            else:
                st.caption("当前条件没有数据。")

        if total_rows == 0:
            record(audit_path, operator_id=operator_id, report_key=report.key, filters=filters, status="success", row_count=0)
            st.info("当前条件没有数据，无需生成 Excel。")
            return

        excel_data = dataframes_to_excel(export_sheets)
        record(audit_path, operator_id=operator_id, report_key=report.key, filters=filters, status="success", row_count=total_rows)
        st.download_button(
            "下载 Excel",
            data=excel_data,
            file_name=create_filename(report.name),
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
    except ReadonlyAccountError as exc:
        record(audit_path, operator_id=operator_id, report_key=report.key, filters=filters, status="failure", error_summary="Readonly account validation failed")
        st.error(str(exc))
        st.warning("系统已拒绝执行 SQL Server 查询；请使用配置白名单中的专用只读账号。")
    except (DatabaseConnectionError, QueryExecutionError, ValueError) as exc:
        record(audit_path, operator_id=operator_id, report_key=report.key, filters=filters, status="failure", error_summary=str(exc))
        st.error(str(exc))
    except Exception:
        # 页面不暴露底层异常，避免泄露内部结构或敏感配置。
        record(audit_path, operator_id=operator_id, report_key=report.key, filters=filters, status="failure", error_summary="Unexpected application error")
        st.error("系统处理失败，请联系管理员并提供操作时间。")


if __name__ == "__main__":
    main()
