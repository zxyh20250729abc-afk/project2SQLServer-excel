from streamlit.testing.v1 import AppTest


def test_first_release_has_no_personal_identity_or_saved_query_controls():
    app = AppTest.from_file("app.py")
    app.run(timeout=10)

    assert not app.exception
    assert "姓名或工号" not in [item.label for item in app.text_input]
    assert "保存为我的常用查询" not in [item.label for item in app.text_input]
    assert "数据查询助手" in [item.value for item in app.title]


def test_builder_provides_additional_business_filter_rows():
    app = AppTest.from_file("app.py")
    app.run(timeout=10)
    app.button(key="start_finance_expense_invoice").click().run(timeout=10)

    assert not app.exception
    assert [item.value for item in app.subheader][:2] == ["1. 选择要查看的信息", "2. 设置查询条件"]
    assert "匹配方式和筛选值怎么填写？" in [item.label for item in app.expander]
    assert "＋ 添加一项条件" in [item.label for item in app.button]

    app.button(key="add_additional_filter_finance_expense_invoice").click().run(timeout=10)
    assert "筛选字段（可搜索）" in [item.label for item in app.selectbox]
