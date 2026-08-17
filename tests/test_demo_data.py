from demo_data import filter_demo_employees, load_demo_employees
from reports import OutputFilter


def test_demo_data_has_expected_columns_and_rows():
    dataframe = load_demo_employees()
    assert len(dataframe) == 180
    assert list(dataframe.columns) == ["人员编号", "姓", "名", "年龄", "部门", "薪资"]


def test_demo_filter_applies_department_and_age_range():
    dataframe = load_demo_employees()
    result = filter_demo_employees(
        dataframe,
        department="销售部",
        min_age=25,
        max_age=40,
    )
    assert all(result["部门"] == "销售部")
    assert all(result["年龄"] >= 25)
    assert all(result["年龄"] <= 40)


def test_demo_filter_supports_multiple_approved_output_conditions():
    result = filter_demo_employees(
        load_demo_employees(),
        department=None,
        min_age=None,
        max_age=None,
        output_filters=(
            OutputFilter("部门", "部门", "equals", "销售部"),
            OutputFilter("薪资", "薪资", "gte", "10000"),
        ),
        approved_columns=("部门", "薪资"),
    )
    assert all(result["部门"] == "销售部")
    assert all(result["薪资"] >= 10000)
