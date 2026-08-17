"""面向业务人员的 SQL Server 只读数据查询助手。"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import streamlit as st

from audit import record
from catalog import DatasetPresentation, available_datasets, get_dataset
from database import (
    DatabaseConnectionError,
    QueryExecutionError,
    ReadonlyAccountError,
    count_rows,
    fetch_export,
    fetch_preview,
    get_output_columns,
    readonly_connection,
)
from demo_data import filter_demo_employees, load_demo_employees
from discovery import DiscoveredFilter, discover_demo_employee_filters, discover_employee_filters
from exporter import create_filename, dataframes_to_excel
from reports import OutputFilter, ReportDefinition, build_filtered_sheet, build_params, get_report


VIEW_KEY = "current_view"
DATASET_KEY = "current_dataset_key"
RESULT_KEY = "last_query_result"
PREVIEW_SIGNATURE_KEY = "last_preview_signature"
INITIAL_PREVIEW_SIGNATURE_KEY = "initial_preview_signature"
PREVIEW_ERROR_KEY = "last_preview_error"
EXCEL_DATA_KEY = "last_excel_data"
EXCEL_FILENAME_KEY = "last_excel_filename"
AUDIT_OPERATOR = "匿名访问"
ADDITIONAL_FILTER_ROWS_KEY = "additional_filter_rows"
ADDITIONAL_FILTER_COUNTER_KEY = "additional_filter_counter"

_NUMERIC_FIELD_HINTS = ("金额", "税额", "税率", "薪资", "年龄", "管理费")
_DATE_FIELD_HINTS = ("日期", "时间")
_OPERATOR_HELP = {
    "contains": "包含：只要字段内容中出现所填文字即可，例如填写“华东”可匹配“华东一区”。",
    "equals": "等于：字段内容必须与所填内容完全一致，例如“财务部”不会匹配“财务共享中心”。",
    "gte": "大于等于：适用于金额、税额等数字字段，结果包含所填数字本身。",
    "lte": "小于等于：适用于金额、税额等数字字段，结果包含所填数字本身。",
    "date_gte": "开始日期：查询该日期当天及之后的数据。",
    "date_lte": "结束日期：查询该日期当天及之前的数据。",
}


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
    st.session_state.setdefault(PREVIEW_SIGNATURE_KEY, None)
    st.session_state.setdefault(INITIAL_PREVIEW_SIGNATURE_KEY, None)
    st.session_state.setdefault(PREVIEW_ERROR_KEY, None)
    st.session_state.setdefault(EXCEL_DATA_KEY, None)
    st.session_state.setdefault(EXCEL_FILENAME_KEY, None)


def filter_widget_key(report_key: str, filter_key: str) -> str:
    return f"filter_{report_key}_{filter_key}"


def field_widget_key(report_key: str) -> str:
    return f"fields_{report_key}"


def additional_filter_rows_key(report_key: str) -> str:
    return f"{ADDITIONAL_FILTER_ROWS_KEY}_{report_key}"


def additional_filter_counter_key(report_key: str) -> str:
    return f"{ADDITIONAL_FILTER_COUNTER_KEY}_{report_key}"


def _add_additional_filter_row(report_key: str) -> None:
    """添加稳定编号的一行条件，以便同一字段可配置上下限两次。"""
    rows_key = additional_filter_rows_key(report_key)
    counter_key = additional_filter_counter_key(report_key)
    next_row_id = int(st.session_state.get(counter_key, 0)) + 1
    st.session_state[counter_key] = next_row_id
    st.session_state.setdefault(rows_key, []).append(next_row_id)
    clear_last_result()


def _remove_additional_filter_row(report_key: str, row_id: int) -> None:
    rows_key = additional_filter_rows_key(report_key)
    st.session_state[rows_key] = [item for item in st.session_state.get(rows_key, []) if item != row_id]
    clear_last_result()


def _clear_additional_filters(report_key: str) -> None:
    """展示字段变化后清空旧条件，保证条件只能来自当前已选信息。"""
    st.session_state[additional_filter_rows_key(report_key)] = []
    clear_last_result()


def additional_filter_widget_key(report_key: str, row_id: int, part: str) -> str:
    return f"additional_filter_{report_key}_{row_id}_{part}"


def clear_last_result() -> None:
    st.session_state[RESULT_KEY] = None
    st.session_state[PREVIEW_SIGNATURE_KEY] = None
    st.session_state[PREVIEW_ERROR_KEY] = None
    clear_excel_export()


def clear_excel_export() -> None:
    """清除过期的完整导出文件，避免条件变化后下载旧数据。"""
    st.session_state[EXCEL_DATA_KEY] = None
    st.session_state[EXCEL_FILENAME_KEY] = None


def reset_query_workspace() -> None:
    """进入或离开查询事项时重置首次展示状态。"""
    clear_last_result()
    st.session_state[INITIAL_PREVIEW_SIGNATURE_KEY] = None


def choose_dataset(dataset_key: str) -> None:
    st.session_state[DATASET_KEY] = dataset_key
    st.session_state[VIEW_KEY] = "builder"
    reset_query_workspace()
    st.rerun()


def go_home() -> None:
    st.session_state[VIEW_KEY] = "home"
    reset_query_workspace()
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
    # 查询设置位于工作台左侧，采用两列避免控件和业务文字过于拥挤。
    columns = st.columns(min(max(len(report.filters), 1), 2))

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


def _field_supports_numeric_filter(field: Any) -> bool:
    business_text = f"{field.label} {field.description}"
    return any(hint in business_text for hint in _NUMERIC_FIELD_HINTS)


def _field_supports_date_filter(field: Any) -> bool:
    business_text = f"{field.label} {field.description}"
    return any(hint in business_text for hint in _DATE_FIELD_HINTS)


def _output_filter_label(output_filter: OutputFilter) -> str:
    operator_labels = {
        "contains": "包含",
        "equals": "等于",
        "gte": "大于等于",
        "lte": "小于等于",
        "date_gte": "从",
        "date_lte": "至",
    }
    return f"{output_filter.label}{operator_labels.get(output_filter.operator, output_filter.operator)}“{output_filter.value.strip()}”"


def _filter_value_placeholder(field: Any) -> str:
    if _field_supports_numeric_filter(field):
        return "例如：10000 或 10000.50"
    return "例如：财务部、华东、INV-2026"


def _filter_value_help(field: Any) -> str:
    if _field_supports_numeric_filter(field):
        return "请只填写数字，可使用小数点；不要填写“≥”“≤”、逗号、货币符号或单位。比较方式请在左侧选择。"
    return "请填写要查找的文字；不需要输入 %、_ 等通配符，系统会将它们按普通文字处理。"


def render_additional_filters(
    dataset: DatasetPresentation,
    selected_fields: list[str],
) -> tuple[list[OutputFilter], str | None]:
    """仅按已选展示字段添加受控条件，页面从不接收 SQL 或底层字段名输入。"""
    rows_key = additional_filter_rows_key(dataset.report_key)
    row_ids: list[int] = list(st.session_state.get(rows_key, []))
    st.session_state.setdefault(rows_key, row_ids)
    field_by_column = {field.column_name: field for field in dataset.fields}
    options = tuple(column for column in selected_fields if column in field_by_column)
    if not options:
        st.info("请先在上一步至少选择一项要查看的信息，才能添加筛选条件。")
        return [], None
    output_filters: list[OutputFilter] = []
    errors: list[str] = []
    with st.expander(f"进一步筛选（{len(row_ids)} 项，可选）", expanded=bool(row_ids)):
        st.caption("从已选择的信息中添加条件；所有条件会同时生效。同一字段可分别设置上下限。")
        with st.expander("匹配方式和筛选值怎么填写？", expanded=False):
            st.markdown("- **包含**：查找字段中带有该文字的记录，例如“华东”可以查到“华东一区”。")
            st.markdown("- **等于**：查找完全相同的记录，例如“财务部”不会匹配“财务共享中心”。")
            st.markdown("- **大于等于 / 小于等于**：只用于金额、税额等数字字段；只填数字，例如 `10000` 或 `10000.50`。")
            st.markdown("- **日期字段**：会显示开始日期和结束日期；只填一端也可以，结束日期当天会被包含。")
            st.markdown("- 不要在筛选值中输入 `%`、`_`、`≥`、`≤`、货币符号或单位；比较方式请在页面中选择。")

        for position, row_id in enumerate(row_ids, start=1):
            st.caption(f"条件 {position}")
            field_column_key = additional_filter_widget_key(dataset.report_key, row_id, "column")
            operator_key = additional_filter_widget_key(dataset.report_key, row_id, "operator")
            value_key = additional_filter_widget_key(dataset.report_key, row_id, "value")
            _set_default(field_column_key, options[0])

            field_column = st.selectbox(
                "筛选字段（可搜索）",
                options=options,
                format_func=lambda column: f"{field_by_column[column].label}：{field_by_column[column].description}",
                key=field_column_key,
            )
            field = field_by_column[field_column]
            operator_labels = {"contains": "包含", "equals": "等于", "gte": "大于等于", "lte": "小于等于"}

            if _field_supports_date_filter(field):
                first, second, third = st.columns((4, 4, 1))
                with first:
                    start_date = st.date_input(
                        "开始日期（可选）",
                        value=None,
                        key=additional_filter_widget_key(dataset.report_key, row_id, "start_date"),
                        format="YYYY-MM-DD",
                        help="不填写则不限制开始日期。",
                    )
                with second:
                    end_date = st.date_input(
                        "结束日期（含，可选）",
                        value=None,
                        key=additional_filter_widget_key(dataset.report_key, row_id, "end_date"),
                        format="YYYY-MM-DD",
                        help="不填写则不限制结束日期；填写后，该日期当天也会包含在结果中。",
                    )
                with third:
                    st.write("")
                    st.button("移除", key=additional_filter_widget_key(dataset.report_key, row_id, "remove"), on_click=_remove_additional_filter_row, args=(dataset.report_key, row_id))

                if start_date is not None and end_date is not None and start_date > end_date:
                    errors.append(f"条件 {position} 的开始日期不能晚于结束日期。")
                elif start_date is not None or end_date is not None:
                    if start_date is not None:
                        output_filters.append(OutputFilter(field.column_name, field.label, "date_gte", start_date.isoformat()))
                    if end_date is not None:
                        output_filters.append(OutputFilter(field.column_name, field.label, "date_lte", end_date.isoformat()))
                else:
                    errors.append(f"请填写条件 {position} 的开始日期或结束日期，或移除该条件。")
            else:
                operator_options = ("contains", "equals", "gte", "lte") if _field_supports_numeric_filter(field) else ("contains", "equals")
                first, second, third = st.columns((3, 4, 1))
                with first:
                    if st.session_state.get(operator_key) not in operator_options:
                        st.session_state[operator_key] = operator_options[0]
                    operator = st.selectbox(
                        "匹配方式",
                        options=operator_options,
                        format_func=lambda item: operator_labels[item],
                        key=operator_key,
                        help="选择系统如何比较该字段与您填写的筛选值。",
                    )
                with second:
                    value = st.text_input("筛选值", key=value_key, placeholder=_filter_value_placeholder(field), help=_filter_value_help(field), max_chars=200)
                with third:
                    st.write("")
                    st.button("移除", key=additional_filter_widget_key(dataset.report_key, row_id, "remove"), on_click=_remove_additional_filter_row, args=(dataset.report_key, row_id))

                st.caption(_OPERATOR_HELP[operator])
                if value.strip():
                    output_filters.append(OutputFilter(field.column_name, field.label, operator, value))
                else:
                    errors.append(f"请填写条件 {position} 的“{field.label}”筛选值，或移除该条件。")

        st.button("＋ 添加一项条件", key=f"add_additional_filter_{dataset.report_key}", on_click=_add_additional_filter_row, args=(dataset.report_key,))
    return output_filters, errors[0] if errors else None


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
        on_change=_clear_additional_filters,
        args=(dataset.report_key,),
    )
    with st.expander("字段说明", expanded=False):
        for field in dataset.fields:
            mark = "推荐" if field.recommended else "可选"
            st.markdown(f"**{field.label}**（{mark}）：{field.description}")
    return list(selected)


def query_summary(
    dataset: DatasetPresentation,
    filters: dict[str, Any],
    selected_fields: list[str],
    output_filters: list[OutputFilter],
) -> str:
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
    conditions.extend(_output_filter_label(output_filter) for output_filter in output_filters)
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
    dataset: DatasetPresentation,
    filters: dict[str, Any],
    output_filters: list[OutputFilter],
    selected_fields: list[str],
    sql_settings: dict[str, Any],
    app_settings: dict[str, Any],
    include_export: bool = False,
) -> dict[str, Any]:
    """执行固定的只读查询；实时预览不会读取全量导出数据。"""
    raw_exports: dict[str, Any] = {}
    raw_previews: list[tuple[str, int, Any]] = []
    # 筛选字段必须同时属于业务字段白名单和本次已选择的展示信息。
    approved_columns = tuple(selected_fields)
    applied_filter_sheets: dict[str, tuple[str, ...]] = {}

    if mode == "demo":
        export_data = filter_demo_employees(
            load_demo_employees(),
            **filters,
            output_filters=output_filters,
            approved_columns=approved_columns,
        )
        if include_export:
            raw_exports[report.sheets[0].name] = export_data
        raw_previews.append((report.sheets[0].name, len(export_data), export_data.head(100)))
        applied_filter_sheets[report.sheets[0].name] = tuple(_output_filter_label(item) for item in output_filters)
    else:
        with readonly_connection(sql_settings) as connection:
            max_export_rows = int(app_settings.get("max_export_rows", 1_048_576))
            total_rows = 0
            sheet_counts: list[tuple[Any, int, list[Any]]] = []
            for sheet in report.sheets:
                base_params = build_params(sheet, filters)
                available_columns = get_output_columns(connection, sheet, base_params)
                try:
                    prepared_sheet, output_params, applied_labels = build_filtered_sheet(
                        sheet,
                        output_filters,
                        approved_columns=approved_columns,
                        available_columns=available_columns,
                    )
                except ValueError as exc:
                    raise QueryExecutionError(str(exc)) from exc
                params = [*base_params, *output_params]
                row_count = count_rows(connection, prepared_sheet, params)
                total_rows += row_count
                if include_export and total_rows > max_export_rows:
                    raise QueryExecutionError(f"查询结果超过 {max_export_rows:,} 行，请缩小筛选条件。")
                sheet_counts.append((prepared_sheet, row_count, params))
                applied_filter_sheets[prepared_sheet.name] = applied_labels

            if output_filters and not any(applied_filter_sheets.values()):
                raise QueryExecutionError("所选附加条件不适用于当前查询结果，已停止查询。")

            for sheet, row_count, params in sheet_counts:
                raw_previews.append((sheet.name, row_count, fetch_preview(connection, sheet, params)))
                if include_export:
                    raw_exports[sheet.name] = fetch_export(connection, sheet, params)

    visible_exports: dict[str, Any] = {}
    visible_previews: list[tuple[str, int, Any]] = []
    omitted_sheets: list[str] = []
    for sheet_name, row_count, preview in raw_previews:
        visible_preview = choose_visible_columns(preview, selected_fields)
        if visible_preview is None:
            omitted_sheets.append(sheet_name)
            continue
        if include_export:
            visible_export = choose_visible_columns(raw_exports[sheet_name], selected_fields)
            if visible_export is None:
                omitted_sheets.append(sheet_name)
                continue
            visible_exports[sheet_name] = visible_export
        visible_previews.append((sheet_name, row_count, visible_preview))

    if not visible_previews:
        raise QueryExecutionError("当前选择的字段不适用于该查询结果，请至少选择一项推荐信息。")
    return {
        "report_key": report.key,
        "filters": filters,
        "selected_fields": selected_fields,
        "output_filters": tuple(output_filters),
        "exports": visible_exports,
        "previews": visible_previews,
        "omitted_sheets": omitted_sheets,
        "applied_filter_sheets": applied_filter_sheets,
        "output_filter_labels": tuple(_output_filter_label(item) for item in output_filters),
    }


def preview_signature(
    *,
    mode: str,
    report: ReportDefinition,
    filters: dict[str, Any],
    selected_fields: list[str],
    output_filters: list[OutputFilter],
) -> tuple[Any, ...]:
    """将当前选择转换成可比较的签名，避免无变化时重复查询。"""
    normalized_filters = tuple(
        (key, value.isoformat() if isinstance(value, date) else str(value))
        for key, value in sorted(filters.items())
    )
    normalized_output_filters = tuple(
        (item.column_name, item.operator, item.value.strip()) for item in output_filters
    )
    return mode, report.key, tuple(selected_fields), normalized_filters, normalized_output_filters


def audit_filter_payload(filters: dict[str, Any], output_filters: list[OutputFilter]) -> dict[str, Any]:
    """导出审计只记录业务条件，不记录 SQL、凭据或结果明细。"""
    return {
        **filters,
        "additional_conditions": [
            {"field": item.label, "operator": item.operator, "value": item.value.strip()}
            for item in output_filters
        ],
    }


def render_preview_result(result: dict[str, Any], dataset: DatasetPresentation) -> bool:
    """右侧工作区：保持可见的前 100 行实时预览，返回是否请求全量 Excel。"""
    previews: list[tuple[str, int, Any]] = result["previews"]
    total_rows = sum(row_count for _, row_count, _ in previews)
    st.subheader("实时预览")
    st.caption("左侧字段或条件变更后会自动更新；为保护性能，此处每张表最多展示前 100 行。")
    st.success(f"当前条件共匹配 {total_rows:,} 行。")
    if result["omitted_sheets"]:
        st.caption(f"未展示 {', '.join(result['omitted_sheets'])}，因为当前未选择其中适用的字段。")
    applied_filter_sheets: dict[str, tuple[str, ...]] = result.get("applied_filter_sheets", {})
    output_filter_labels = set(result.get("output_filter_labels", ()))
    if output_filter_labels:
        partial_notes = []
        for sheet_name, labels in applied_filter_sheets.items():
            missing = output_filter_labels - set(labels)
            if missing:
                partial_notes.append(f"{sheet_name} 未套用：{'、'.join(sorted(missing))}")
        if partial_notes:
            st.info("已添加的条件仅作用于包含该字段的工作表；" + "；".join(partial_notes))

    if len(previews) == 1:
        sheet_name, row_count, preview = previews[0]
        if row_count:
            st.caption(f"{sheet_name}｜展示前 {len(preview):,} 行")
            st.dataframe(preview, width="stretch", hide_index=True, height=480)
        else:
            st.info("当前条件没有数据。")
    else:
        tabs = st.tabs([sheet_name for sheet_name, _, _ in previews])
        for tab, (sheet_name, row_count, preview) in zip(tabs, previews):
            with tab:
                if row_count:
                    st.caption(f"展示前 {len(preview):,} 行")
                    st.dataframe(preview, width="stretch", hide_index=True, height=440)
                else:
                    st.info("当前条件没有数据。")

    if total_rows == 0:
        return False

    st.divider()
    st.caption("确认预览无误后，再生成包含全部匹配数据的 Excel 文件。")
    return st.button("生成 Excel（全量数据）", key=f"generate_excel_{result['report_key']}", type="primary", use_container_width=True)


def render_excel_download(dataset: DatasetPresentation) -> None:
    excel_data = st.session_state.get(EXCEL_DATA_KEY)
    filename = st.session_state.get(EXCEL_FILENAME_KEY)
    if not excel_data or not filename:
        return
    st.success("Excel 已生成，可下载。")
    st.download_button(
        "下载 Excel",
        data=excel_data,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
    )


def render_home(mode: str) -> None:
    st.title("数据查询助手")
    render_safety_status(mode)

    datasets = available_datasets(mode)

    normal_datasets = [dataset for dataset in datasets if not dataset.is_system_test]
    if normal_datasets:
        st.subheader("选择业务模块")
        finance_tab, contract_tab = st.tabs(("财务数据", "合同管理"))
        domain_tabs = (("finance", finance_tab, "财务数据"), ("contract", contract_tab, "合同管理"))
        for domain_key, tab, domain_name in domain_tabs:
            with tab:
                domain_datasets = [dataset for dataset in normal_datasets if dataset.domain_key == domain_key]
                if not domain_datasets:
                    st.info(f"未找到“{domain_name}”相关事项。")
                    continue
                st.caption(f"{domain_name} › 选择具体查询事项")
                columns = st.columns(min(2, len(domain_datasets)))
                for index, dataset in enumerate(domain_datasets):
                    with columns[index % len(columns)]:
                        with st.container(border=True):
                            st.markdown(f"**{dataset.title.replace('查询', '')}**")
                            st.caption(dataset.description)
                            if st.button("进入查询", key=f"start_{dataset.report_key}", use_container_width=True):
                                choose_dataset(dataset.report_key)
    else:
        st.info("当前没有可用的业务事项，请联系管理员检查业务模块配置。")

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

    settings_column, preview_column = st.columns((4, 6), gap="large")
    with settings_column:
        with st.container(border=True):
            st.subheader("1. 选择要查看的信息")
            selected_fields = render_field_picker(dataset)
            st.divider()
            st.subheader("2. 设置查询条件")
            st.caption("基础范围用于限定本次查询；进一步筛选只能从上方已选信息中选择。")
            filters, filter_error = render_filters(report, mode, sql_settings)
            if filter_error:
                st.error(filter_error)
            output_filters, output_filter_error = render_additional_filters(dataset, selected_fields)
            st.caption(query_summary(dataset, filters or {}, selected_fields, output_filters))

    is_ready = not filter_error and filters is not None and not output_filter_error and bool(selected_fields)
    signature: tuple[Any, ...] | None = None
    if is_ready:
        signature = preview_signature(
            mode=mode,
            report=report,
            filters=filters,
            selected_fields=selected_fields,
            output_filters=output_filters,
        )
        initial_signature = st.session_state.get(INITIAL_PREVIEW_SIGNATURE_KEY)
        if initial_signature is None:
            # 首次进入只呈现默认条件，不立即对真实业务库发起查询；任一设置变化后实时更新。
            st.session_state[INITIAL_PREVIEW_SIGNATURE_KEY] = signature
            st.session_state[PREVIEW_ERROR_KEY] = None
            preview_error = None
        elif st.session_state.get(PREVIEW_SIGNATURE_KEY) != signature:
            # 条件变更后先撤销旧导出，再只重新读取前 100 行预览。
            clear_excel_export()
            try:
                with st.spinner("正在更新预览..."):
                    result = execute_query(
                        mode=mode,
                        report=report,
                        dataset=dataset,
                        filters=filters,
                        output_filters=output_filters,
                        selected_fields=selected_fields,
                        sql_settings=sql_settings,
                        app_settings=app_settings,
                        include_export=False,
                    )
                st.session_state[RESULT_KEY] = result
                st.session_state[PREVIEW_SIGNATURE_KEY] = signature
                st.session_state[PREVIEW_ERROR_KEY] = None
            except ReadonlyAccountError as exc:
                clear_last_result()
                st.session_state[PREVIEW_SIGNATURE_KEY] = signature
                preview_error = str(exc)
                st.session_state[PREVIEW_ERROR_KEY] = preview_error
            except (DatabaseConnectionError, QueryExecutionError, ValueError) as exc:
                clear_last_result()
                st.session_state[PREVIEW_SIGNATURE_KEY] = signature
                preview_error = str(exc)
                st.session_state[PREVIEW_ERROR_KEY] = preview_error
            except Exception:
                clear_last_result()
                st.session_state[PREVIEW_SIGNATURE_KEY] = signature
                preview_error = "系统处理失败，请联系管理员并提供操作时间。"
                st.session_state[PREVIEW_ERROR_KEY] = preview_error
            else:
                preview_error = None
        else:
            preview_error = st.session_state.get(PREVIEW_ERROR_KEY)
    else:
        clear_excel_export()
        preview_error = filter_error or output_filter_error
        if not selected_fields:
            preview_error = "请至少选择一项要查看的信息。"

    with preview_column:
        with st.container(border=True):
            result = st.session_state.get(RESULT_KEY)
            if preview_error:
                st.subheader("实时预览")
                st.info(preview_error)
            elif result and result.get("report_key") == report.key and st.session_state.get(PREVIEW_SIGNATURE_KEY) == signature:
                export_requested = render_preview_result(result, dataset)
                if export_requested:
                    audit_path = str(app_settings.get("audit_db_path", "audit.db"))
                    audit_filters = audit_filter_payload(filters, output_filters)
                    try:
                        with st.spinner("正在生成完整 Excel..."):
                            export_result = execute_query(
                                mode=mode,
                                report=report,
                                dataset=dataset,
                                filters=filters,
                                output_filters=output_filters,
                                selected_fields=selected_fields,
                                sql_settings=sql_settings,
                                app_settings=app_settings,
                                include_export=True,
                            )
                        total_rows = sum(row_count for _, row_count, _ in export_result["previews"])
                        st.session_state[RESULT_KEY] = export_result
                        st.session_state[EXCEL_DATA_KEY] = dataframes_to_excel(export_result["exports"])
                        st.session_state[EXCEL_FILENAME_KEY] = create_filename(dataset.title.replace("查询", ""))
                        record(audit_path, operator_id=AUDIT_OPERATOR, report_key=report.key, filters=audit_filters, status="success", row_count=total_rows)
                    except ReadonlyAccountError as exc:
                        record(audit_path, operator_id=AUDIT_OPERATOR, report_key=report.key, filters=audit_filters, status="failure", error_summary="Readonly account validation failed")
                        st.error(str(exc))
                        st.warning("系统已阻止导出；请使用 DBA 配置的专用只读账号。")
                    except (DatabaseConnectionError, QueryExecutionError, ValueError) as exc:
                        record(audit_path, operator_id=AUDIT_OPERATOR, report_key=report.key, filters=audit_filters, status="failure", error_summary=str(exc))
                        st.error(str(exc))
                    except Exception:
                        record(audit_path, operator_id=AUDIT_OPERATOR, report_key=report.key, filters=audit_filters, status="failure", error_summary="Unexpected application error")
                        st.error("生成 Excel 失败，请联系管理员并提供操作时间。")
                render_excel_download(dataset)
            else:
                st.subheader("实时预览")
                st.caption("请选择要查看的信息并设置有效条件，结果会自动显示在这里。")


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
