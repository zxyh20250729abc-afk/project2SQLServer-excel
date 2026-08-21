import inspect
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from app import apply_theme, localize_missing_values

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def test_first_release_has_no_personal_identity_or_saved_query_controls():
    app = AppTest.from_file(APP_PATH)
    app.run(timeout=10)

    assert not app.exception
    assert "姓名或工号" not in [item.label for item in app.text_input]
    assert "保存为我的常用查询" not in [item.label for item in app.text_input]
    assert not app.text_input
    assert "数据查询助手" in [item.value for item in app.title]
    assert "选择业务模块" in [item.value for item in app.subheader]


def test_builder_provides_additional_business_filter_rows():
    app = AppTest.from_file(APP_PATH)
    app.run(timeout=10)
    app.button(key="start_finance_expense_invoice").click().run(timeout=10)

    assert not app.exception
    assert [item.value for item in app.subheader][:2] == ["1. 选择要查看的信息", "2. 设置查询条件"]
    assert "匹配方式和筛选值怎么填写？" in [item.label for item in app.expander]
    assert "＋ 增加筛选条件" in [item.label for item in app.button]
    assert "全选" in [item.label for item in app.button]
    assert "清空" in [item.label for item in app.button]
    assert not app.date_input
    assert "开始日期（含）－年份" in [item.label for item in app.selectbox]
    assert "结束日期（含）－年份" in [item.label for item in app.selectbox]
    assert "查询预览" not in [item.label for item in app.button]

    app.button(key="add_additional_filter_finance_expense_invoice").click().run(timeout=10)
    assert "筛选字段（可搜索）" in [item.label for item in app.selectbox]


def test_missing_preview_values_are_displayed_in_chinese_without_mutating_source():
    source = pd.DataFrame({"备注": [None, "已归档"], "金额": [None, 100]})

    displayed = localize_missing_values(source)

    assert displayed.iloc[0].tolist() == ["null", "null"]
    assert source.iloc[0].isna().all()


def test_dark_theme_covers_current_streamlit_input_layers():
    theme_css_source = inspect.getsource(apply_theme)

    assert '[data-baseweb="base-input"]' in theme_css_source
    assert '[data-testid="stTextInputRootElement"]' in theme_css_source
    assert '[data-testid="stSelectbox"] [role="group"]' in theme_css_source
    assert "background-color: #1a2230 !important" in theme_css_source
    assert "input:-webkit-autofill" in theme_css_source
    assert "background-color: transparent !important" in theme_css_source
    assert '.stApp input[type="text"]' in theme_css_source


def test_enterprise_theme_has_accessible_interaction_and_responsive_tokens():
    theme_css_source = inspect.getsource(apply_theme)

    assert "--app-bg" in theme_css_source
    assert "--text-primary" in theme_css_source
    assert "min-height: 44px" in theme_css_source
    assert "focus-visible" in theme_css_source
    assert "prefers-reduced-motion: reduce" in theme_css_source
    assert "@media (max-width: 760px)" in theme_css_source
    assert ".react-aria-SelectionIndicator" in theme_css_source
