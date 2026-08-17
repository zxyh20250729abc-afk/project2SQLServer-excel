"""面向业务人员的 SQL Server 只读数据查询助手。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st

from audit import record
from catalog import DatasetPresentation, available_datasets, get_dataset, search_datasets
from database import DatabaseConnectionError, QueryExecutionError, ReadonlyAccountError, count_rows, fetch_export, fetch_preview, readonly_connection
from demo_data import filter_demo_employees, load_demo_employees
from discovery import DiscoveredFilter, discover_demo_employee_filters, discover_employee_filters
from exporter import create_filename, dataframes_to_excel
from reports import ReportDefinition, build_params, get_report


VIEW_KEY = "current_view"
DATASET_KEY = "current_dataset_key"
RESULT_KEY = "last_query_result"
AUDIT_OPERATOR = "匿名访问"


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


def initialize_session() -> None:
    st.session_state.setdefault(VIEW_KEY, "home")
    st.session_state.setdefault(DATASET_KEY, None)
    st.session_state.setdefault(RESULT_KEY, None)


def filter_widget_key(report_key: str, filter_key: str) -> str:
    return f"filter_{report_key}_{filter_key}"


def field_widget_key(report_key: str) -> str:
    return f"fields_{report_key}"


def clear_last_result() -> None:
    st.session_state[RESULT_KEY] = None


def choose_dataset(dataset_key: str) -> None:
    st.session_state[DATASET_KEY] = dataset_key
    st.session_state[VIEW_KEY] = "builder"
    clear_last_result()
    st.rerun()


def go_home() -> None:
    st.session_state[VIEW_KEY] = "home"
    clear_last_result()
    st.rerun()


def render_safety_status(mode: str) -> None:
    if mode == "sqlserver":
        st.info("🔒 当前为只读查询：系统只读取已批准的数据，不支持修改、删除、建表或执行任意 SQL。")
    else:
        st.info("🧪 当前为模拟数据模式：可体验查询和 Excel 导出，不会连接 SQL Server。")


def parse_optional_age(value: str, field_name: str) -> tuple[int | None, str | None]:
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
    """员工测试数据的部门候选值仅通过固定只读查询获取。"""
    if mode == "demo":
        return discover_demo_employee_filters(load_demo_employees())
    with readonly_connection(sql_settings) as connection:
        return discover_employee_filters(connection)


def _set_default(widget_key: str, value: Any) -> None:
    if widget_key not in st.session_state:
        st.session_state[widget_key] = value


def render_employee_filters(mode: str, sql_settings: dict[str, Any], report_key: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        definitions = get_employee_filter_definitions(mode, sql_settings)
    except (DatabaseConnectionError, ReadonlyAccountError, QueryExecutionError) as exc:
        return None, f"无法读取测试数据筛选项：{exc}"

    by_key = {item.key: item for item in definitions}
    if "department" not in by_key or "age" not in by_key:
        return None, "测试数据未包含必要筛选项，已停止查询。"

    col1, col2, col3 = st.columns(3)
    with col1:
        department_key = filter_widget_key(report_key, "department")
        _set_default(department_key, "全部")
        department = st.selectbox(f"{by_key['department'].label}（可选）", options=("全部", *by_key["department"].options), key=department_key)
    with col2:
        minimum_key = filter_widget_key(report_key, "min_age")
        _set_default(minimum_key, "")
        min_age_text = st.text_input("最小年龄（可选）", max_chars=3, key=minimum_key)
    with col3:
        maximum_key = filter_widget_key(report_key, "max_age")
        _set_default(maximum_key, "")
        max_age_text = st.text_input("最大年龄（可选）", max_chars=3, key=maximum_key)

    min_age, min_error = parse_optional_age(min_age_text, "最小年龄")
    max_age, max_error = parse_optional_age(max_age_text, "最大年龄")
    if min_error or max_error:
        return None, min_error or max_error
    if min_age is not None and max_age is not None and min_age > max_age:
        return None, "最小年龄不能大于最大年龄。"
    return {"department": None if department == "全部" else department, "min_age": min_age, "max_age": max_age}, None


def _default_date_range() -> tuple[date, date]:
    start_date = date.today().replace(day=1)
    end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start_date, end_date


def friendly_filter_label(filter_key: str, fallback: str) -> str:
    labels = {
        "year": "入账年份",
        "start_month": "起始月份",
        "end_month": "结束月份",
        "start_date": "开始日期（含）",
        "end_date": "结束日期（不含）",
    }
    return labels.get(filter_key, fallback)


def render_business_filters(report: ReportDefinition) -> tuple[dict[str, Any], str | None]:
    """按业务语言展示已批准的年度、月份或日期条件。"""
    values: dict[str, Any] = {}
    default_start, default_end = _default_date_range()
    columns = st.columns(min(max(len(report.filters), 1), 3))

    for index, definition in enumerate(report.filters):
        widget_key = filter_widget_key(report.key, definition.key)
        label = friendly_filter_label(definition.key, definition.label)
        with columns[index % len(columns)]:
            if definition.kind == "date":
                _set_default(widget_key, default_start if definition.key == "start_date" else default_end)
                values[definition.key] = st.date_input(label, key=widget_key)
            elif definition.kind == "month":
                options = tuple(range(int(definition.minimum or 1), int(definition.maximum or 12) + 1))
                _set_default(widget_key, date.today().month)
                values[definition.key] = st.selectbox(label, options=options, key=widget_key)
            elif definition.kind == "integer":
                options = tuple(range(int(definition.minimum or 0), int(definition.maximum or 9999) + 1))
                _set_default(widget_key, date.today().year if date.today().year in options else options[0])
                values[definition.key] = st.selectbox(label, options=options, key=widget_key)
            else:
                return values, "查询条件配置错误，已停止查询。"

    if "start_month" in values and "end_month" in values and values["start_month"] > values["end_month"]:
        return values, "起始月份不能晚于结束月份。"
    if "start_date" in values and "end_date" in values and values["start_date"] >= values["end_date"]:
        return values, "结束日期必须晚于开始日期。"
    return values, None


def render_filters(report: ReportDefinition, mode: str, sql_settings: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if report.key == "employee_list":
        return render_employee_filters(mode, sql_settings, report.key)
    return render_business_filters(report)


def render_field_picker(dataset: DatasetPresentation) -> list[str]:
    """展示中文字段目录；用户选择展示和导出的内容，而非数据库列。"""
    options = tuple(field.column_name for field in dataset.fields)
    widget_key = field_widget_key(dataset.report_key)
    _set_default(widget_key, [field.column_name for field in dataset.fields if field.recommended])
    selected = st.multiselect(
        "我想查看哪些信息？",
        options=options,
        format_func=lambda column: next(field.label for field in dataset.fields if field.column_name == column),
        key=widget_key,
        help="系统只会展示和导出您选择的业务信息。",
    )
    with st.expander("字段说明", expanded=False):
        for field in dataset.fields:
            mark = "推荐" if field.recommended else "可选"
            st.markdown(f"**{field.label}**（{mark}）：{field.description}")
    return list(selected)


def query_summary(dataset: DatasetPresentation, filters: dict[str, Any], selected_fields: list[str]) -> str:
    filter_labels = {
        "year": "入账年份",
        "start_month": "起始月份",
        "end_month": "结束月份",
        "start_date": "开始日期",
        "end_date": "结束日期",
        "department": "部门",
        "min_age": "最小年龄",
        "max_age": "最大年龄",
    }
    conditions = []
    for key, value in filters.items():
        if value is not None and value != "":
            formatted = value.isoformat() if isinstance(value, date) else str(value)
            conditions.append(f"{filter_labels.get(key, key)}为 {formatted}")
    field_labels = [field.label for field in dataset.fields if field.column_name in selected_fields]
    return f"将查询“{dataset.title}”，{'；'.join(conditions) or '不限定筛选条件'}，展示 {len(field_labels)} 项业务信息。"


def choose_visible_columns(dataframe: Any, selected_fields: list[str]) -> Any | None:
    columns = [column for column in selected_fields if column in dataframe.columns]
    if not columns:
        return None
    return dataframe.loc[:, columns].copy()


def execute_query(
    *,
    mode: str,
    report: ReportDefinition,
    filters: dict[str, Any],
    selected_fields: list[str],
    sql_settings: dict[str, Any],
    app_settings: dict[str, Any],
) -> dict[str, Any]:
    """执行固定的只读查询，再仅保留用户选中的业务字段。"""
    raw_exports: dict[str, Any] = {}
    raw_previews: list[tuple[str, int, Any]] = []

    if mode == "demo":
        export_data = filter_demo_employees(load_demo_employees(), **filters)
        raw_exports[report.sheets[0].name] = export_data
        raw_previews.append((report.sheets[0].name, len(export_data), export_data.head(100)))
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
                raw_previews.append((sheet.name, row_count, fetch_preview(connection, sheet, params)))
                raw_exports[sheet.name] = fetch_export(connection, sheet, params)

    visible_exports: dict[str, Any] = {}
    visible_previews: list[tuple[str, int, Any]] = []
    omitted_sheets: list[str] = []
    for sheet_name, row_count, preview in raw_previews:
        visible_preview = choose_visible_columns(preview, selected_fields)
        visible_export = choose_visible_columns(raw_exports[sheet_name], selected_fields)
        if visible_preview is None or visible_export is None:
            omitted_sheets.append(sheet_name)
            continue
        visible_exports[sheet_name] = visible_export
        visible_previews.append((sheet_name, row_count, visible_preview))

    if not visible_exports:
        raise QueryExecutionError("当前选择的字段不适用于该查询结果，请至少选择一项推荐信息。")
    return {
        "report_key": report.key,
        "filters": filters,
        "selected_fields": selected_fields,
        "exports": visible_exports,
        "previews": visible_previews,
        "omitted_sheets": omitted_sheets,
    }


def render_query_result(result: dict[str, Any], dataset: DatasetPresentation) -> None:
    previews: list[tuple[str, int, Any]] = result["previews"]
    total_rows = sum(row_count for _, row_count, _ in previews)
    st.divider()
    st.subheader("查询结果")
    st.success(f"查询完成，共 {total_rows:,} 行。数据仅来自您有权限访问的范围。")
    if result["omitted_sheets"]:
        st.caption(f"未展示 {', '.join(result['omitted_sheets'])}，因为当前未选择其中适用的字段。")

    for sheet_name, row_count, preview in previews:
        st.markdown(f"##### {sheet_name}")
        if row_count:
            st.caption(f"展示前 {len(preview):,} 行")
            st.dataframe(preview, width="stretch", hide_index=True)
        else:
            st.caption("当前条件没有数据。")

    if total_rows == 0:
        st.info("当前条件没有数据。您可以返回上方调整日期、部门或其他条件。")
        return

    excel_data = dataframes_to_excel(result["exports"])
    st.download_button(
        "下载 Excel",
        data=excel_data,
        file_name=create_filename(dataset.title.replace("查询", "")),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
    )


def render_home(mode: str) -> None:
    st.title("数据查询助手")
    st.caption("用业务语言查数据：选择事项、填写条件、预览后导出 Excel。")
    render_safety_status(mode)

    query_text = st.text_input("您想查询什么？", placeholder="例如：报销发票、合同金额、认款明细")
    datasets = search_datasets(available_datasets(mode), query_text)

    normal_datasets = [dataset for dataset in datasets if not dataset.is_system_test]
    if normal_datasets:
        st.subheader("按业务事项开始")
        domains: dict[str, list[DatasetPresentation]] = {}
        for dataset in normal_datasets:
            domains.setdefault(dataset.domain_name, []).append(dataset)
        for domain_name, domain_datasets in domains.items():
            st.markdown(f"#### {domain_name}")
            columns = st.columns(min(3, len(domain_datasets)))
            for index, dataset in enumerate(domain_datasets):
                with columns[index % len(columns)]:
                    with st.container(border=True):
                        st.markdown(f"**{dataset.title}**")
                        st.caption(dataset.description)
                        if st.button("开始查询", key=f"start_{dataset.report_key}", use_container_width=True):
                            choose_dataset(dataset.report_key)
    else:
        st.info("没有找到匹配的业务事项。可尝试“报销”“合同”“认款”等关键词。")

    test_datasets = [dataset for dataset in datasets if dataset.is_system_test]
    if test_datasets:
        with st.expander("系统验证（管理员使用）", expanded=(mode == "demo")):
            for dataset in test_datasets:
                st.caption(dataset.description)
                if st.button("打开测试数据", key=f"test_{dataset.report_key}"):
                    choose_dataset(dataset.report_key)


def render_builder(dataset: DatasetPresentation, mode: str, sql_settings: dict[str, Any], app_settings: dict[str, Any]) -> None:
    report = get_report(dataset.report_key)
    if st.button("← 返回首页"):
        go_home()

    if dataset.is_system_test and mode != "demo":
        st.warning("员工测试数据只用于本机演示和管理员连通性核验，不属于真实业务库。请返回首页，选择“财务数据”或“合同管理”中的业务事项。")
        return

    st.title(dataset.title)
    st.caption(dataset.description)
    st.caption("系统会自动关联已批准的业务数据；您无需了解数据表或字段名称。")
    render_safety_status(mode)

    with st.form(f"query_form_{dataset.report_key}"):
        st.subheader("1. 选择查询条件")
        filters, filter_error = render_filters(report, mode, sql_settings)
        if filter_error:
            # 不能再把筛选项读取失败隐藏到点击查询之后，避免页面出现空白条件区。
            st.error(filter_error)
        st.subheader("2. 选择要查看的信息")
        selected_fields = render_field_picker(dataset)
        st.caption(query_summary(dataset, filters or {}, selected_fields))
        submitted = st.form_submit_button("查询预览", type="primary")

    if submitted:
        audit_path = str(app_settings.get("audit_db_path", "audit.db"))
        if filter_error:
            st.warning(filter_error)
            return
        if filters is None:
            st.error("无法生成查询条件，已停止查询。")
            return
        if not selected_fields:
            st.warning("请至少选择一项要查看的信息。")
            return

        try:
            with st.spinner("正在准备数据..."):
                result = execute_query(
                    mode=mode,
                    report=report,
                    filters=filters,
                    selected_fields=selected_fields,
                    sql_settings=sql_settings,
                    app_settings=app_settings,
                )
            total_rows = sum(row_count for _, row_count, _ in result["previews"])
            record(audit_path, operator_id=AUDIT_OPERATOR, report_key=report.key, filters=filters, status="success", row_count=total_rows)
            st.session_state[RESULT_KEY] = result
        except ReadonlyAccountError as exc:
            record(audit_path, operator_id=AUDIT_OPERATOR, report_key=report.key, filters=filters, status="failure", error_summary="Readonly account validation failed")
            st.error(str(exc))
            st.warning("系统已阻止查询；请使用 DBA 配置的专用只读账号。")
        except (DatabaseConnectionError, QueryExecutionError, ValueError) as exc:
            record(audit_path, operator_id=AUDIT_OPERATOR, report_key=report.key, filters=filters, status="failure", error_summary=str(exc))
            st.error(str(exc))
        except Exception:
            record(audit_path, operator_id=AUDIT_OPERATOR, report_key=report.key, filters=filters, status="failure", error_summary="Unexpected application error")
            st.error("系统处理失败，请联系管理员并提供操作时间。")

    result = st.session_state.get(RESULT_KEY)
    if result and result.get("report_key") == report.key:
        render_query_result(result, dataset)


def main() -> None:
    st.set_page_config(page_title="数据查询助手", page_icon="📊", layout="wide")
    initialize_session()
    try:
        mode, sql_settings, app_settings = get_settings()
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    if st.session_state[VIEW_KEY] == "builder" and st.session_state.get(DATASET_KEY):
        try:
            dataset = get_dataset(st.session_state[DATASET_KEY])
        except ValueError:
            go_home()
            return
        render_builder(dataset, mode, sql_settings, app_settings)
    else:
        render_home(mode)


if __name__ == "__main__":
    main()
