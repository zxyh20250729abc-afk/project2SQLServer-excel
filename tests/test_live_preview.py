from app import execute_query
from catalog import get_dataset
from reports import get_report


def test_demo_preview_does_not_load_full_export_until_requested():
    dataset = get_dataset("employee_list")
    report = get_report(dataset.report_key)
    selected_fields = ["人员编号", "部门", "年龄"]
    filters = {"department": "销售部", "min_age": None, "max_age": None}

    preview = execute_query(
        mode="demo",
        report=report,
        dataset=dataset,
        filters=filters,
        output_filters=[],
        selected_fields=selected_fields,
        sql_settings={},
        app_settings={},
        include_export=False,
    )

    assert preview["exports"] == {}
    assert preview["previews"][0][1] == 45
    assert list(preview["previews"][0][2].columns) == selected_fields

    full_export = execute_query(
        mode="demo",
        report=report,
        dataset=dataset,
        filters=filters,
        output_filters=[],
        selected_fields=selected_fields,
        sql_settings={},
        app_settings={},
        include_export=True,
    )

    assert list(full_export["exports"]["员工信息"].columns) == selected_fields
    assert len(full_export["exports"]["员工信息"]) == 45
