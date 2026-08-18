from datetime import date

import pytest

from reports import (
    EMPLOYEE_REPORT,
    REPORTS,
    OutputFilter,
    available_reports,
    build_filtered_sheet,
    build_params,
    get_report,
    validate_read_only_sql,
    validate_sheet_read_only,
)


def test_build_params_keeps_user_values_as_parameters():
    params = build_params(
        EMPLOYEE_REPORT.sheets[0],
        {"department": "销售部", "min_age": 25, "max_age": 40},
    )
    assert params == ["销售部", "销售部", 25, 25, 40, 40]


def test_business_reports_are_versioned_and_read_only():
    business_reports = [report for report in REPORTS.values() if not report.supports_demo]
    assert len(business_reports) == 6
    for report in business_reports:
        approved = get_report(report.key)
        assert approved.sheets
        for sheet in approved.sheets:
            assert "@" not in sheet.data_sql
            validate_read_only_sql(sheet.data_sql)
            validate_read_only_sql(sheet.page_sql)
            validate_read_only_sql(sheet.count_sql)


def test_date_parameters_are_bound_in_fixed_order():
    report = get_report("contract_amount_summary")
    params = build_params(
        report.sheets[0],
        {"start_date": date(2026, 1, 1), "end_date": date(2026, 2, 1)},
    )
    assert params == [date(2026, 1, 1), date(2026, 2, 2), date(2026, 1, 1), date(2026, 2, 2)]


def test_all_business_reports_use_start_and_end_dates():
    business_reports = [report for report in REPORTS.values() if not report.supports_demo]
    for report in business_reports:
        assert [item.key for item in report.filters] == ["start_date", "end_date"]


def test_page_queries_are_limited_to_fifty_rows_by_bound_parameters():
    for report in REPORTS.values():
        for sheet in report.sheets:
            assert "OFFSET ? ROWS FETCH NEXT ? ROWS ONLY" in sheet.page_sql
            validate_read_only_sql(sheet.page_sql)


def test_demo_mode_hides_real_business_reports():
    assert [report.key for report in available_reports("demo")] == ["employee_list"]
    assert len(available_reports("sqlserver")) == 7


def test_unknown_report_is_rejected():
    with pytest.raises(ValueError):
        get_report("unapproved")


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE dbo.orders SET status = 'done'",
        "SELECT * FROM dbo.orders; DELETE FROM dbo.orders",
        "SELECT * FROM dbo.orders -- appended command",
        "EXEC dbo.export_orders",
        "SELECT * INTO dbo.copy_orders FROM dbo.orders",
    ],
)
def test_non_readonly_sql_is_rejected(sql):
    with pytest.raises(ValueError):
        validate_read_only_sql(sql)


def test_simple_select_sql_is_allowed():
    validate_read_only_sql("SELECT personid FROM dbo.employees WHERE age >= ?")


def test_output_filters_are_parameterized_and_remain_read_only():
    sheet, params, labels = build_filtered_sheet(
        EMPLOYEE_REPORT.sheets[0],
        (
            OutputFilter("部门", "部门", "contains", "销售%部"),
            OutputFilter("年龄", "年龄", "gte", "25"),
        ),
        approved_columns=("人员编号", "部门", "年龄"),
        available_columns=("人员编号", "部门", "年龄"),
    )

    assert "WHERE CONVERT(nvarchar(max), [部门]) LIKE ?" in sheet.data_sql
    assert "TRY_CONVERT(decimal(38, 10), [年龄]) >= ?" in sheet.data_sql
    assert params[0] == "%销售\\%部%"
    assert str(params[1]) == "25"
    assert labels == ("部门包含“销售%部”", "年龄大于等于25")
    validate_sheet_read_only(sheet)


def test_date_range_filters_include_the_selected_end_day():
    sheet, params, labels = build_filtered_sheet(
        EMPLOYEE_REPORT.sheets[0],
        (
            OutputFilter("申请时间", "申请时间", "date_gte", "2026-01-01"),
            OutputFilter("申请时间", "申请时间", "date_lte", "2026-01-31"),
        ),
        approved_columns=("申请时间",),
        available_columns=("申请时间",),
    )

    assert "TRY_CONVERT(date, [申请时间]) >= ?" in sheet.data_sql
    assert "TRY_CONVERT(date, [申请时间]) < DATEADD(day, 1, ?)" in sheet.data_sql
    assert params == [date(2026, 1, 1), date(2026, 1, 31)]
    assert labels == ("申请时间从2026-01-01起", "申请时间至2026-01-31止")
    validate_sheet_read_only(sheet)


def test_output_filter_rejects_unapproved_fields_and_invalid_numbers():
    with pytest.raises(ValueError):
        build_filtered_sheet(
            EMPLOYEE_REPORT.sheets[0],
            (OutputFilter("不存在", "不存在", "equals", "x"),),
            approved_columns=("部门",),
            available_columns=("部门",),
        )
    with pytest.raises(ValueError):
        build_filtered_sheet(
            EMPLOYEE_REPORT.sheets[0],
            (OutputFilter("年龄", "年龄", "gte", "不是数字"),),
            approved_columns=("年龄",),
            available_columns=("年龄",),
        )
    with pytest.raises(ValueError):
        build_filtered_sheet(
            EMPLOYEE_REPORT.sheets[0],
            (OutputFilter("申请时间", "申请时间", "date_gte", "2026-99-99"),),
            approved_columns=("申请时间",),
            available_columns=("申请时间",),
        )
    with pytest.raises(ValueError):
        build_filtered_sheet(
            EMPLOYEE_REPORT.sheets[0],
            (OutputFilter("年龄", "年龄", "gte", "NaN"),),
            approved_columns=("年龄",),
            available_columns=("年龄",),
        )
