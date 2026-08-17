from streamlit.testing.v1 import AppTest


def test_first_release_has_no_personal_identity_or_saved_query_controls():
    app = AppTest.from_file("app.py")
    app.run(timeout=10)

    assert not app.exception
    assert "姓名或工号" not in [item.label for item in app.text_input]
    assert "保存为我的常用查询" not in [item.label for item in app.text_input]
    assert "数据查询助手" in [item.value for item in app.title]
