"""面向业务人员的 SQL Server 只读数据查询助手。"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from html import escape
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
    fetch_page,
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
PAGE_KEY = "preview_page"
BASE_SIGNATURE_KEY = "last_query_base_signature"
THEME_KEY = "display_theme"
PAGE_SIZE = 50
APP_VERSION = "3.0"

_NUMERIC_FIELD_HINTS = ("金额", "税额", "税率", "薪资", "年龄", "管理费")
_DATE_FIELD_HINTS = ("日期", "时间")
_DATE_YEAR_OPTIONS = tuple(range(1900, 2101))
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
    st.session_state.setdefault(THEME_KEY, "跟随系统")


def filter_widget_key(report_key: str, filter_key: str) -> str:
    return f"filter_{report_key}_{filter_key}"


def field_widget_key(report_key: str) -> str:
    return f"fields_{report_key}"


def additional_filter_rows_key(report_key: str) -> str:
    return f"{ADDITIONAL_FILTER_ROWS_KEY}_{report_key}"


def additional_filter_counter_key(report_key: str) -> str:
    return f"{ADDITIONAL_FILTER_COUNTER_KEY}_{report_key}"


def page_widget_key(report_key: str) -> str:
    return f"{PAGE_KEY}_{report_key}"


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
    st.session_state[BASE_SIGNATURE_KEY] = None


def _change_page(report_key: str, page: int) -> None:
    st.session_state[page_widget_key(report_key)] = max(1, page)


def _select_all_fields(report_key: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        st.session_state[f"field_choice_{report_key}_{column}"] = True
    _clear_additional_filters(report_key)


def _clear_all_fields(report_key: str, columns: tuple[str, ...]) -> None:
    for column in columns:
        st.session_state[f"field_choice_{report_key}_{column}"] = False
    _clear_additional_filters(report_key)


def apply_theme() -> None:
    """应用中文主题选择；跟随系统时使用浏览器的系统颜色偏好。"""
    theme = st.session_state.get(THEME_KEY, "跟随系统")
    light = """
        :root {
            color-scheme: light;
            --app-bg: #f4f7fb;
            --surface: #ffffff;
            --surface-subtle: #f8fafc;
            --surface-strong: #edf3fb;
            --text-primary: #162033;
            --text-secondary: #526077;
            --border: #dbe3ef;
            --border-strong: #c5d1e1;
            --primary: #1e4f91;
            --primary-hover: #183f74;
            --primary-soft: #eaf2fc;
            --success: #19724a;
            --success-soft: #e9f7f0;
            --warning: #9a5b08;
            --warning-soft: #fff6e6;
            --danger: #b4232f;
            --shadow-card: 0 1px 2px rgba(16, 24, 40, .04), 0 8px 24px rgba(31, 56, 88, .06);
        }
        .stApp, [data-testid="stAppViewContainer"] { background: var(--app-bg); color: var(--text-primary); }
        [data-testid="stHeader"] { background: rgba(244,247,251,.94); }
        [data-testid="stVerticalBlockBorderWrapper"] { background: var(--surface); border-color: var(--border); }
    """
    dark = """
        :root {
            color-scheme: dark;
            --app-bg: #0d1420;
            --surface: #131d2a;
            --surface-subtle: #182433;
            --surface-strong: #202e40;
            --text-primary: #f2f6fb;
            --text-secondary: #b4c0d0;
            --border: #2c3b4f;
            --border-strong: #40536c;
            --primary: #76a9e6;
            --primary-hover: #96c0ef;
            --primary-soft: #1b3452;
            --success: #6dd3a1;
            --success-soft: #14362a;
            --warning: #f2bd67;
            --warning-soft: #3b2c15;
            --danger: #ff8993;
            --shadow-card: 0 1px 2px rgba(0, 0, 0, .25), 0 12px 30px rgba(0, 0, 0, .18);
        }
        .stApp, [data-testid="stAppViewContainer"] { background: var(--app-bg); color: var(--text-primary); }
        [data-testid="stHeader"] { background: rgba(13,20,32,.94); }
        [data-testid="stVerticalBlockBorderWrapper"] { background: var(--surface); border-color: var(--border); }
        /* Streamlit 版本升级后输入控件会多一层 BaseWeb 容器，内外层都需要设置深色。 */
        [data-testid="stTextInput"] [data-baseweb="input"],
        [data-testid="stNumberInput"] [data-baseweb="input"],
        [data-testid="stDateInput"] [data-baseweb="input"],
        [data-testid="stTextInput"] [data-baseweb="base-input"],
        [data-testid="stNumberInput"] [data-baseweb="base-input"],
        [data-testid="stDateInput"] [data-baseweb="base-input"],
        [data-testid="stTextInputRootElement"],
        [data-testid="stNumberInput"] [role="group"],
        [data-testid="stDateInput"] [role="group"],
        [data-testid="stSelectbox"] [role="group"],
        [data-testid="stMultiSelect"] [role="group"],
        [data-testid="stSelectbox"] [data-baseweb="select"] > div,
        [data-testid="stMultiSelect"] [data-baseweb="select"] > div,
        [data-testid="stTextArea"] textarea {
            background-color: #1a2230 !important;
            color: #f8fafc !important;
            border-color: #3f4b5f !important;
            box-shadow: none !important;
        }
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input,
        [data-testid="stDateInput"] input,
        [data-testid="stTextArea"] textarea,
        [data-testid="stSelectbox"] [role="group"] *,
        [data-testid="stMultiSelect"] [role="group"] *,
        [data-testid="stSelectbox"] [data-baseweb="select"] *,
        [data-testid="stMultiSelect"] [data-baseweb="select"] * {
            color: #f8fafc !important;
        }
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input,
        [data-testid="stDateInput"] input {
            background-color: transparent !important;
            caret-color: #f8fafc !important;
        }
        /* 兼容服务器上不同 Streamlit 版本的输入框 DOM 结构。 */
        .stApp input[type="text"],
        .stApp input[type="number"],
        .stApp input[type="date"],
        .stApp textarea {
            background-color: #1a2230 !important;
            color: #f8fafc !important;
            caret-color: #f8fafc !important;
        }
        [data-testid="stNumberInput"] button {
            background-color: #232d3d !important;
            color: #dbe5f3 !important;
            border-color: #3f4b5f !important;
        }
        [data-testid="stTextInput"] [data-baseweb="input"]:focus-within,
        [data-testid="stNumberInput"] [data-baseweb="input"]:focus-within,
        [data-testid="stDateInput"] [data-baseweb="input"]:focus-within,
        [data-testid="stTextInputRootElement"]:focus-within,
        [data-testid="stNumberInput"] [role="group"]:focus-within,
        [data-testid="stDateInput"] [role="group"]:focus-within,
        [data-testid="stSelectbox"] [role="group"]:focus-within,
        [data-testid="stMultiSelect"] [role="group"]:focus-within,
        [data-testid="stSelectbox"] [data-baseweb="select"] > div:focus-within,
        [data-testid="stMultiSelect"] [data-baseweb="select"] > div:focus-within {
            border-color: #6c9bd2 !important;
            box-shadow: 0 0 0 1px #6c9bd2 !important;
        }
        [data-testid="stTextInput"] input:-webkit-autofill,
        [data-testid="stNumberInput"] input:-webkit-autofill,
        [data-testid="stDateInput"] input:-webkit-autofill {
            -webkit-text-fill-color: #f8fafc !important;
            -webkit-box-shadow: 0 0 0 1000px #1a2230 inset !important;
            caret-color: #f8fafc !important;
        }
        [data-testid="stTextInput"] input::placeholder,
        [data-testid="stNumberInput"] input::placeholder,
        [data-testid="stDateInput"] input::placeholder,
        [data-testid="stTextArea"] textarea::placeholder {
            color: #9aa6b8 !important;
            opacity: 1;
        }
        [data-baseweb="popover"] [role="listbox"],
        [data-baseweb="menu"],
        [role="listbox"] {
            background: #1a2230 !important;
            color: #f8fafc !important;
        }
        [data-baseweb="popover"] [role="option"],
        [role="listbox"] [role="option"] { color: #f8fafc !important; }
        [data-baseweb="popover"] [role="option"]:hover,
        [role="listbox"] [role="option"]:hover { background: #26364a !important; }
    """
    if theme == "白天":
        palette = light
    elif theme == "夜间":
        palette = dark
    else:
        palette = light + f"@media (prefers-color-scheme: dark) {{ {dark} }}"
    st.markdown(
        f"""
        <style>
        {palette}
        [data-testid="stHeader"], [data-testid="stToolbar"], #MainMenu, footer {{ display: none !important; }}
        html, body, [class*="css"] {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
        }}
        .stApp {{ font-size: 16px; line-height: 1.55; }}
        .block-container {{
            max-width: 1540px;
            padding-top: 1.25rem;
            padding-bottom: 3rem;
        }}
        h1, h2, h3 {{ color: var(--text-primary) !important; letter-spacing: -.02em; }}
        h1 {{ font-size: clamp(1.75rem, 2.4vw, 2.35rem) !important; line-height: 1.22 !important; margin-bottom: .35rem !important; }}
        h2 {{ font-size: 1.25rem !important; line-height: 1.35 !important; }}
        h3 {{ font-size: 1.08rem !important; line-height: 1.4 !important; }}
        p, label, [data-testid="stCaptionContainer"] {{ color: var(--text-secondary); }}
        [data-testid="stCaptionContainer"] {{ font-size: .875rem; line-height: 1.55; }}
        .page-kicker {{
            color: var(--primary);
            font-size: .76rem;
            font-weight: 700;
            letter-spacing: .12em;
            margin: .35rem 0 .45rem;
            text-transform: uppercase;
        }}
        .page-lead {{
            color: var(--text-secondary);
            font-size: 1rem;
            line-height: 1.7;
            margin: -.1rem 0 .9rem;
            max-width: 70ch;
        }}
        [data-testid="stVerticalBlockBorderWrapper"] {{
            border-radius: 14px !important;
            box-shadow: var(--shadow-card);
        }}
        [data-testid="stButton"] button,
        [data-testid="stDownloadButton"] button {{
            min-height: 44px;
            border-radius: 10px;
            border-color: var(--border-strong);
            font-weight: 600;
            transition: background-color .16s ease, border-color .16s ease, color .16s ease, box-shadow .16s ease;
            touch-action: manipulation;
        }}
        [data-testid="stButton"] button:hover,
        [data-testid="stDownloadButton"] button:hover {{
            background: var(--primary-soft);
            border-color: var(--primary);
            color: var(--primary);
            box-shadow: 0 2px 8px rgba(30,79,145,.12);
        }}
        [data-testid="stButton"] button[kind="secondary"],
        [data-testid="stDownloadButton"] button[kind="secondary"] {{
            background: var(--surface);
            color: var(--text-primary);
        }}
        [data-testid="stButton"] button:focus-visible,
        [data-testid="stDownloadButton"] button:focus-visible,
        input:focus-visible,
        textarea:focus-visible {{
            outline: 2px solid var(--primary) !important;
            outline-offset: 2px !important;
        }}
        [data-testid="stButton"] button[kind="primary"],
        [data-testid="stDownloadButton"] button[kind="primary"] {{
            background: #1e4f91;
            border-color: #1e4f91;
            color: #ffffff;
        }}
        [data-testid="stButton"] button[kind="primary"]:hover,
        [data-testid="stDownloadButton"] button[kind="primary"]:hover {{
            background: #183f74;
            border-color: #183f74;
            color: #ffffff;
        }}
        [data-testid="stButton"] button:disabled {{ opacity: .46; cursor: not-allowed; }}
        [data-testid="stTextInput"] input,
        [data-testid="stNumberInput"] input,
        [data-testid="stDateInput"] input,
        [data-testid="stSelectbox"] [data-baseweb="select"] > div,
        [data-testid="stMultiSelect"] [data-baseweb="select"] > div {{
            min-height: 44px;
            border-radius: 9px !important;
        }}
        [data-testid="stWidgetLabel"] p {{ color: var(--text-primary); font-weight: 600; }}
        [data-testid="stTabs"] [role="tablist"] {{
            gap: .25rem;
            border-bottom: 1px solid var(--border);
        }}
        [data-testid="stTabs"] [role="tab"] {{
            min-height: 44px;
            padding-inline: 1.1rem;
            color: var(--text-secondary);
            font-weight: 600;
        }}
        [data-testid="stTabs"] [role="tab"][aria-selected="true"] {{ color: var(--primary); }}
        [data-testid="stTabs"] .react-aria-SelectionIndicator {{ background: var(--primary) !important; }}
        [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type {{
            background: var(--primary) !important;
            border-color: var(--primary) !important;
        }}
        [data-testid="stAlert"] {{ border-radius: 11px; border: 1px solid var(--border); }}
        [data-testid="stDataFrame"] {{ border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }}
        [data-testid="stMetric"] {{
            background: var(--surface-subtle);
            border: 1px solid var(--border);
            border-radius: 11px;
            padding: .75rem 1rem;
        }}
        [data-testid="stMetricValue"] {{ color: var(--text-primary); font-variant-numeric: tabular-nums; }}
        .st-key-topbar {{
            border-bottom: 1px solid var(--border);
            margin-bottom: 1.25rem;
            padding-bottom: .75rem;
        }}
        .st-key-topbar [data-testid="stCaptionContainer"] {{ color: var(--text-primary); font-weight: 700; }}
        [class*="st-key-dataset_card_"] {{ min-height: 188px; }}
        [class*="st-key-dataset_card_"] [data-testid="stVerticalBlock"] {{ height: 100%; }}
        [class*="st-key-selected_summary_"] {{
            background: var(--primary-soft);
            border: 1px solid color-mix(in srgb, var(--primary) 28%, var(--border));
            border-radius: 10px;
            gap: .35rem !important;
            margin-top: .6rem;
            padding: .7rem .8rem .85rem;
        }}
        [class*="st-key-selected_summary_"] p {{ margin: 0; }}
        [class*="st-key-selected_summary_"] [data-testid="stMarkdownContainer"],
        [class*="st-key-selected_summary_"] [data-testid="stCaptionContainer"] {{
            margin-bottom: 0 !important;
        }}
        .st-key-query_controls,
        .st-key-results_workspace {{ align-self: start; }}
        .st-key-additional_filter_panel {{
            background: var(--surface-subtle);
            border: 1px solid var(--border-strong) !important;
            border-left: 3px solid var(--primary) !important;
            border-radius: 11px !important;
            padding: .65rem .85rem .85rem !important;
            box-shadow: none;
        }}
        .st-key-additional_filter_panel h3 {{ color: var(--text-primary) !important; }}
        .query-summary {{
            background: var(--surface-strong);
            border: 1px solid var(--border);
            border-radius: 10px;
            color: var(--text-secondary);
            font-size: .875rem;
            line-height: 1.6;
            margin-top: .75rem;
            padding: .7rem .8rem;
        }}
        .query-summary strong {{ color: var(--text-primary); }}
        .empty-preview {{
            background: var(--surface-subtle);
            border: 1px dashed var(--border-strong);
            border-radius: 12px;
            margin-top: .8rem;
            padding: 1.4rem;
        }}
        .empty-preview strong {{ color: var(--text-primary); display: block; margin-bottom: .3rem; }}
        .empty-preview span {{ color: var(--text-secondary); font-size: .9rem; line-height: 1.6; }}
        @media (max-width: 760px) {{
            .block-container {{ padding: 1rem 1rem 2rem; }}
            h1 {{ font-size: 1.7rem !important; }}
            [class*="st-key-dataset_card_"] {{ min-height: auto; }}
            [data-testid="stHorizontalBlock"] {{ gap: .75rem; }}
            .st-key-topbar [data-testid="stCaptionContainer"] {{ display: none; }}
        }}
        @media (prefers-reduced-motion: reduce) {{
            *, *::before, *::after {{ scroll-behavior: auto !important; transition-duration: .01ms !important; animation-duration: .01ms !important; }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_theme_selector() -> None:
    """在页面右上方显示全中文的显示模式选择。"""
    with st.container(key="topbar"):
        brand, selector = st.columns((7, 3), vertical_alignment="bottom")
        with brand:
            st.caption("企业数据查询中心 · 只读访问")
        with selector:
            st.selectbox(
                "显示模式",
                options=("跟随系统", "白天", "夜间"),
                key=THEME_KEY,
                help="选择页面的明暗外观。",
            )
    apply_theme()


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
        st.info("只读安全模式：系统只读取已批准的数据，不支持修改、删除、建表或执行任意 SQL。")
    else:
        st.info("模拟数据模式：可体验查询和 Excel 导出，不会连接 SQL Server。")


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
    end_date = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return start_date, end_date


def friendly_filter_label(filter_key: str, fallback: str) -> str:
    labels = {
        "year": "入账年份",
        "start_month": "起始月份",
        "end_month": "结束月份",
        "start_date": "开始日期（含）",
        "end_date": "结束日期（含）",
    }
    return labels.get(filter_key, fallback)


def render_chinese_date_input(
    label: str,
    *,
    key: str,
    value: date | None,
    optional: bool = False,
    help_text: str | None = None,
) -> date | None:
    """使用中文年、月、日选择器，避免原生日历按浏览器显示英文。"""
    default_value = value or date.today()
    year_key = f"{key}_year"
    month_key = f"{key}_month"
    day_key = f"{key}_day"
    year_options: tuple[int | None, ...] = ((None,) + _DATE_YEAR_OPTIONS) if optional else _DATE_YEAR_OPTIONS
    _set_default(year_key, None if optional and value is None else default_value.year)
    _set_default(month_key, default_value.month)

    st.markdown(f"**{label}**")
    year_column, month_column, day_column = st.columns(3, gap="small")
    with year_column:
        selected_year = st.selectbox(
            f"{label}－年份",
            options=year_options,
            key=year_key,
            format_func=lambda item: "不限" if item is None else f"{item}年",
            label_visibility="collapsed",
            help=help_text,
        )
    active_year = int(selected_year) if selected_year is not None else default_value.year
    with month_column:
        selected_month = st.selectbox(
            f"{label}－月份",
            options=tuple(range(1, 13)),
            key=month_key,
            format_func=lambda item: f"{item}月",
            label_visibility="collapsed",
            disabled=selected_year is None,
        )

    maximum_day = monthrange(active_year, int(selected_month))[1]
    previous_day = int(st.session_state.get(day_key, default_value.day))
    if previous_day > maximum_day:
        st.session_state[day_key] = maximum_day
    else:
        _set_default(day_key, previous_day)
    with day_column:
        selected_day = st.selectbox(
            f"{label}－日期",
            options=tuple(range(1, maximum_day + 1)),
            key=day_key,
            format_func=lambda item: f"{item}日",
            label_visibility="collapsed",
            disabled=selected_year is None,
        )

    if selected_year is None:
        return None
    return date(int(selected_year), int(selected_month), int(selected_day))


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
                values[definition.key] = render_chinese_date_input(
                    label,
                    key=widget_key,
                    value=default_start if definition.key == "start_date" else default_end,
                )
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
    if "start_date" in values and "end_date" in values and values["start_date"] > values["end_date"]:
        return values, "结束日期不能早于开始日期。"
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
    with st.container(border=True, key="additional_filter_panel"):
        st.subheader("增加筛选条件")
        st.caption(f"已添加 {len(row_ids)} 项（可选） · 条件仅从已选择的信息中产生，并会同时生效。")
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
                first, second, third = st.columns((4, 4, 1.5))
                with first:
                    start_date = render_chinese_date_input(
                        "开始日期（可选）",
                        optional=True,
                        value=None,
                        key=additional_filter_widget_key(dataset.report_key, row_id, "start_date"),
                        help_text="年份保持“不限”时，不限制开始日期。",
                    )
                with second:
                    end_date = render_chinese_date_input(
                        "结束日期（含，可选）",
                        optional=True,
                        value=None,
                        key=additional_filter_widget_key(dataset.report_key, row_id, "end_date"),
                        help_text="年份保持“不限”时，不限制结束日期；选择后会包含当天。",
                    )
                with third:
                    st.write("")
                    st.button(
                        "移除",
                        key=additional_filter_widget_key(dataset.report_key, row_id, "remove"),
                        on_click=_remove_additional_filter_row,
                        args=(dataset.report_key, row_id),
                        use_container_width=True,
                    )

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
                first, second, third = st.columns((3, 4, 1.5))
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
                    st.button(
                        "移除",
                        key=additional_filter_widget_key(dataset.report_key, row_id, "remove"),
                        on_click=_remove_additional_filter_row,
                        args=(dataset.report_key, row_id),
                        use_container_width=True,
                    )

                st.caption(_OPERATOR_HELP[operator])
                if value.strip():
                    output_filters.append(OutputFilter(field.column_name, field.label, operator, value))
                else:
                    errors.append(f"请填写条件 {position} 的“{field.label}”筛选值，或移除该条件。")

        st.button(
            "＋ 增加筛选条件",
            key=f"add_additional_filter_{dataset.report_key}",
            on_click=_add_additional_filter_row,
            args=(dataset.report_key,),
            use_container_width=True,
        )
    return output_filters, errors[0] if errors else None


def render_field_picker(dataset: DatasetPresentation) -> list[str]:
    """使用全中文字段选择器，避免原生多选框出现英文提示。"""
    options = tuple(field.column_name for field in dataset.fields)
    field_by_column = {field.column_name: field for field in dataset.fields}
    snapshot_key = field_widget_key(dataset.report_key)
    if snapshot_key not in st.session_state:
        st.session_state[snapshot_key] = [field.column_name for field in dataset.fields if field.recommended]
    previous = list(st.session_state[snapshot_key])
    previous_set = set(previous)
    for field in dataset.fields:
        _set_default(f"field_choice_{dataset.report_key}_{field.column_name}", field.column_name in previous_set)

    st.markdown("**我想查看哪些信息？**")
    actions = st.columns((4, 1.2, 1.2))
    with actions[0]:
        search = st.text_input(
            "搜索信息",
            key=f"field_search_{dataset.report_key}",
            placeholder="输入名称查找，例如：金额、日期、部门",
        )
    with actions[1]:
        st.write("")
        st.button(
            "全选",
            key=f"select_all_fields_{dataset.report_key}",
            on_click=_select_all_fields,
            args=(dataset.report_key, options),
            use_container_width=True,
        )
    with actions[2]:
        st.write("")
        st.button(
            "清空",
            key=f"clear_all_fields_{dataset.report_key}",
            on_click=_clear_all_fields,
            args=(dataset.report_key, options),
            use_container_width=True,
        )

    normalized_search = search.strip().casefold()
    visible_fields = [
        field
        for field in dataset.fields
        if not normalized_search
        or normalized_search in f"{field.label} {field.description}".casefold()
    ]
    if not visible_fields:
        st.info("无结果")
    else:
        with st.container(height=250, border=True):
            columns = st.columns(2)
            for index, field in enumerate(visible_fields):
                with columns[index % 2]:
                    st.checkbox(
                        field.label,
                        key=f"field_choice_{dataset.report_key}_{field.column_name}",
                        help=field.description,
                    )

    selected = [
        column
        for column in options
        if st.session_state.get(f"field_choice_{dataset.report_key}_{column}", False)
    ]
    if selected != previous:
        st.session_state[snapshot_key] = selected
        _clear_additional_filters(dataset.report_key)
    selected_labels = [field_by_column[column].label for column in selected]
    selected_text = "、".join(selected_labels) if selected_labels else "尚未选择"
    with st.container(key=f"selected_summary_{dataset.report_key}"):
        st.markdown(f"**已选择 {len(selected)} 项**")
        st.caption(selected_text)
    with st.expander("字段说明", expanded=False):
        for field in dataset.fields:
            mark = "推荐" if field.recommended else "可选"
            st.markdown(f"**{field.label}**（{mark}）：{field.description}")
    return selected


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
    page: int = 1,
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
        page_start = (page - 1) * PAGE_SIZE
        raw_previews.append((report.sheets[0].name, len(export_data), export_data.iloc[page_start : page_start + PAGE_SIZE]))
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
                raw_previews.append(
                    (
                        sheet.name,
                        row_count,
                        fetch_page(connection, sheet, params, page=page, page_size=PAGE_SIZE),
                    )
                )
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
        "page": page,
        "page_size": PAGE_SIZE,
    }


def preview_signature(
    *,
    mode: str,
    report: ReportDefinition,
    filters: dict[str, Any],
    selected_fields: list[str],
    output_filters: list[OutputFilter],
    page: int = 1,
) -> tuple[Any, ...]:
    """将当前选择转换成可比较的签名，避免无变化时重复查询。"""
    normalized_filters = tuple(
        (key, value.isoformat() if isinstance(value, date) else str(value))
        for key, value in sorted(filters.items())
    )
    normalized_output_filters = tuple(
        (item.column_name, item.operator, item.value.strip()) for item in output_filters
    )
    return mode, report.key, tuple(selected_fields), normalized_filters, normalized_output_filters, page


def audit_filter_payload(filters: dict[str, Any], output_filters: list[OutputFilter]) -> dict[str, Any]:
    """导出审计只记录业务条件，不记录 SQL、凭据或结果明细。"""
    return {
        **filters,
        "additional_conditions": [
            {"field": item.label, "operator": item.operator, "value": item.value.strip()}
            for item in output_filters
        ],
    }


def localize_missing_values(dataframe: Any) -> Any:
    """仅为页面预览将真实空值显示为 null，不修改查询结果。"""
    return dataframe.astype(object).where(dataframe.notna(), "null")


def render_preview_result(result: dict[str, Any], dataset: DatasetPresentation) -> bool:
    """右侧工作区：每页最多 50 行实时预览，返回是否请求全量 Excel。"""
    previews: list[tuple[str, int, Any]] = result["previews"]
    total_rows = sum(row_count for _, row_count, _ in previews)
    current_page = int(result.get("page", 1))
    page_size = int(result.get("page_size", PAGE_SIZE))
    total_pages = max(1, max(((row_count + page_size - 1) // page_size for _, row_count, _ in previews), default=1))
    st.subheader("实时预览")
    st.caption(f"左侧字段或条件变更后会自动更新；结果按每页最多 {page_size} 行显示。")
    result_metrics = st.columns(2)
    with result_metrics[0]:
        st.metric("匹配记录", f"{total_rows:,} 行")
    with result_metrics[1]:
        st.metric("分页进度", f"{current_page:,} / {total_pages:,}")
    navigation = st.columns((1, 2, 1))
    with navigation[0]:
        st.button(
            "← 上一页",
            key=f"previous_page_{result['report_key']}_{current_page}",
            disabled=current_page <= 1,
            on_click=_change_page,
            args=(result["report_key"], current_page - 1),
            use_container_width=True,
        )
    with navigation[1]:
        st.markdown(f"<p style='text-align:center;margin:.55rem 0'>第 {current_page:,} 页，共 {total_pages:,} 页</p>", unsafe_allow_html=True)
    with navigation[2]:
        st.button(
            "下一页 →",
            key=f"next_page_{result['report_key']}_{current_page}",
            disabled=current_page >= total_pages,
            on_click=_change_page,
            args=(result["report_key"], current_page + 1),
            use_container_width=True,
        )
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
            st.caption(f"{sheet_name}｜本页 {len(preview):,} 行")
            st.dataframe(localize_missing_values(preview), width="stretch", hide_index=True, height=480)
        else:
            st.info("当前条件没有数据。")
    else:
        tabs = st.tabs([sheet_name for sheet_name, _, _ in previews])
        for tab, (sheet_name, row_count, preview) in zip(tabs, previews):
            with tab:
                if row_count:
                    st.caption(f"本页 {len(preview):,} 行")
                    st.dataframe(localize_missing_values(preview), width="stretch", hide_index=True, height=440)
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
    render_theme_selector()
    st.markdown('<div class="page-kicker">Enterprise Data Workspace</div>', unsafe_allow_html=True)
    st.title("数据查询助手")
    st.markdown(
        f'<div class="page-lead">通过业务语言完成安全、只读的数据查询与 Excel 导出。无需了解数据表、字段名或 SQL。 · V{APP_VERSION}</div>',
        unsafe_allow_html=True,
    )
    render_safety_status(mode)

    datasets = available_datasets(mode)

    normal_datasets = [dataset for dataset in datasets if not dataset.is_system_test]
    if normal_datasets:
        st.subheader("选择业务模块")
        st.caption("先选择业务领域，再进入具体查询事项。")
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
                        with st.container(border=True, key=f"dataset_card_{dataset.report_key}"):
                            st.caption(f"{domain_name} · 只读查询")
                            st.markdown(f"### {dataset.title.replace('查询', '')}")
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
    render_theme_selector()
    if st.button("← 返回业务模块", key="back_to_home"):
        go_home()

    if dataset.is_system_test and mode != "demo":
        st.warning("员工测试数据只用于本机演示和管理员连通性核验，不属于真实业务库。请返回首页，选择“财务数据”或“合同管理”中的业务事项。")
        return

    domain_name = "财务数据" if dataset.domain_key == "finance" else "合同管理"
    st.markdown(f'<div class="page-kicker">{escape(domain_name)} / 业务查询</div>', unsafe_allow_html=True)
    st.title(dataset.title)
    st.markdown(
        f'<div class="page-lead">{escape(dataset.description)} 系统会自动关联已批准的数据，您无需了解数据表或字段名称。</div>',
        unsafe_allow_html=True,
    )
    render_safety_status(mode)

    settings_column, preview_column = st.columns((4, 6), gap="large")
    with settings_column:
        with st.container(border=True, key="query_controls"):
            st.subheader("1. 选择要查看的信息")
            selected_fields = render_field_picker(dataset)
            st.divider()
            st.subheader("2. 设置查询条件")
            st.caption("基础范围用于限定本次查询；增加筛选条件时只能从上方已选信息中选择。")
            filters, filter_error = render_filters(report, mode, sql_settings)
            if filter_error:
                st.error(filter_error)
            output_filters, output_filter_error = render_additional_filters(dataset, selected_fields)
            summary = escape(query_summary(dataset, filters or {}, selected_fields, output_filters))
            st.markdown(
                f'<div class="query-summary"><strong>当前查询摘要</strong><br>{summary}</div>',
                unsafe_allow_html=True,
            )

    is_ready = not filter_error and filters is not None and not output_filter_error and bool(selected_fields)
    signature: tuple[Any, ...] | None = None
    if is_ready:
        current_page_key = page_widget_key(report.key)
        st.session_state.setdefault(current_page_key, 1)
        base_signature = preview_signature(
            mode=mode,
            report=report,
            filters=filters,
            selected_fields=selected_fields,
            output_filters=output_filters,
            page=1,
        )
        if st.session_state.get(BASE_SIGNATURE_KEY) not in {None, base_signature}:
            st.session_state[current_page_key] = 1
        st.session_state[BASE_SIGNATURE_KEY] = base_signature
        current_page = int(st.session_state[current_page_key])
        signature = preview_signature(
            mode=mode,
            report=report,
            filters=filters,
            selected_fields=selected_fields,
            output_filters=output_filters,
            page=current_page,
        )
        initial_signature = st.session_state.get(INITIAL_PREVIEW_SIGNATURE_KEY)
        if initial_signature is None:
            # 首次进入只呈现默认条件，不立即对真实业务库发起查询；任一设置变化后实时更新。
            st.session_state[INITIAL_PREVIEW_SIGNATURE_KEY] = signature
            st.session_state[PREVIEW_ERROR_KEY] = None
            preview_error = None
        elif st.session_state.get(PREVIEW_SIGNATURE_KEY) != signature:
            # 条件或页码变更后先撤销旧导出，再只读取当前 50 行预览。
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
                        page=current_page,
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
        with st.container(border=True, key="results_workspace"):
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
                                page=current_page,
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
                st.caption("查询结果会在设置变化后自动刷新。")
                st.markdown(
                    '<div class="empty-preview"><strong>结果区已就绪</strong><span>在左侧确认查看字段和查询条件。任一设置发生变化后，系统将在此显示分页结果。</span></div>',
                    unsafe_allow_html=True,
                )


def main() -> None:
    st.set_page_config(page_title="数据查询助手", layout="wide", initial_sidebar_state="collapsed")
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
