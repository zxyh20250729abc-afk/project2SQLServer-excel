"""project2SQLServer导入excel系统 MVP 入口。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st

from audit import record
from database import DatabaseConnectionError, QueryExecutionError, ReadonlyAccountError, count_rows, fetch_export, fetch_preview, readonly_connection
from demo_data import filter_demo_orders, load_demo_orders
from exporter import create_filename, dataframe_to_excel
from reports import build_params, get_report


REPORT_KEY = "order_detail"


def get_settings() -> tuple[str, dict[str, Any], dict[str, Any]]:
    """读取运行模式和配置；缺少密钥文件时安全回退到演示模式。"""
    try:
        app_settings = dict(st.secrets.get("app", {}))
        mode = str(app_settings.get("mode", "demo")).lower()
        sql_settings = dict(st.secrets.get("sqlserver", {}))
    except (FileNotFoundError, KeyError) as exc:
        return "demo", {}, {}

    if mode not in {"demo", "sqlserver"}:
        raise RuntimeError("app.mode 只能设置为 demo 或 sqlserver。")
    if mode == "sqlserver" and not sql_settings:
        raise RuntimeError("SQL Server 模式缺少数据库配置。请检查 .streamlit/secrets.toml。")
    return mode, sql_settings, app_settings


def validate_inputs(operator_id: str, start_date: date, end_date: date, max_range_days: int) -> str | None:
    if not operator_id.strip():
        return "请输入姓名或工号，用于导出审计。"
    if end_date < start_date:
        return "结束日期不能早于开始日期。"
    if (end_date - start_date).days + 1 > max_range_days:
        return f"单次查询日期范围不能超过 {max_range_days} 天。"
    return None


def main() -> None:
    st.set_page_config(page_title="project2SQLServer导入excel系统", page_icon="📊", layout="wide")
    st.title("project2SQLServer导入excel系统")
    st.caption("MVP：受控条件查询 · SQL Server 只读访问 · Excel 导出")

    try:
        mode, sql_settings, app_settings = get_settings()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    report = get_report(REPORT_KEY)
    st.subheader(report.name)
    st.caption(report.description)
    if mode == "demo":
        st.info("当前为模拟数据模式：可完整体验筛选、预览和 Excel 下载；数据不会连接 SQL Server。")
    else:
        st.caption(report.source_note)

    with st.form("query_form"):
        operator_id = st.text_input("姓名或工号", max_chars=100, help="仅用于导出审计。")
        col1, col2, col3, col4 = st.columns(4)
        today = date.today()
        with col1:
            start_date = st.date_input("开始日期", value=today - timedelta(days=6))
        with col2:
            end_date = st.date_input("结束日期", value=today)
        with col3:
            department = st.text_input("部门（可选）", max_chars=100).strip() or None
        with col4:
            status = st.selectbox("状态（可选）", options=["全部", "待处理", "已完成", "已取消"])
            status = None if status == "全部" else status
        submitted = st.form_submit_button("查询预览", type="primary")

    if not submitted:
        return

    max_range_days = int(app_settings.get("max_date_range_days", 31))
    validation_error = validate_inputs(operator_id, start_date, end_date, max_range_days)
    if validation_error:
        st.warning(validation_error)
        return

    filters = {"start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "department": department, "status": status}
    params = build_params(start_date, end_date + timedelta(days=1), department, status)
    audit_path = str(app_settings.get("audit_db_path", "audit.db"))

    try:
        with st.spinner("正在准备数据..."):
            if mode == "demo":
                export_data = filter_demo_orders(
                    load_demo_orders(),
                    start_date=start_date,
                    end_date=end_date,
                    department=department,
                    status=status,
                )
                row_count = len(export_data)
                preview = export_data.head(100)
            else:
                with readonly_connection(sql_settings) as connection:
                    row_count = count_rows(connection, report, params)
                    max_export_rows = int(app_settings.get("max_export_rows", 1_048_576))
                    if row_count > max_export_rows:
                        raise QueryExecutionError(f"查询结果超过 {max_export_rows:,} 行，请缩小日期范围或筛选条件。")
                    preview = fetch_preview(connection, report, params)
                    export_data = fetch_export(connection, report, params)
        st.success(f"查询完成，共 {row_count:,} 行。以下展示前 {len(preview):,} 行。")
        st.dataframe(preview, width="stretch", hide_index=True)

        if row_count == 0:
            record(audit_path, operator_id=operator_id, report_key=REPORT_KEY, filters=filters, status="success", row_count=0)
            st.info("当前条件没有数据，无需生成 Excel。")
            return

        excel_data = dataframe_to_excel(export_data, sheet_name=report.name)
        filename = create_filename(report.name, start_date, end_date)
        record(audit_path, operator_id=operator_id, report_key=REPORT_KEY, filters=filters, status="success", row_count=row_count)
        st.download_button(
            "下载 Excel",
            data=excel_data,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            type="primary",
        )
    except ReadonlyAccountError as exc:
        record(audit_path, operator_id=operator_id, report_key=REPORT_KEY, filters=filters, status="failure", error_summary="Readonly account validation failed")
        st.error(str(exc))
        st.warning("系统已拒绝执行 SQL Server 查询；请使用配置白名单中的专用只读账号。")
    except (DatabaseConnectionError, QueryExecutionError) as exc:
        record(audit_path, operator_id=operator_id, report_key=REPORT_KEY, filters=filters, status="failure", error_summary=str(exc))
        st.error(str(exc))
    except Exception:
        # 页面不暴露底层异常，避免泄露内部结构或敏感配置。
        record(audit_path, operator_id=operator_id, report_key=REPORT_KEY, filters=filters, status="failure", error_summary="Unexpected application error")
        st.error("系统处理失败，请联系管理员并提供操作时间。")


if __name__ == "__main__":
    main()
