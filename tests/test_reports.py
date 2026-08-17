from datetime import date

import pytest

from reports import EMPLOYEE_REPORT, REPORTS, available_reports, build_params, get_report, validate_read_only_sql


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
            validate_read_only_sql(sheet.preview_sql)
            validate_read_only_sql(sheet.count_sql)


def test_date_parameters_are_bound_in_fixed_order():
    report = get_report("contract_amount_summary")
    params = build_params(
        report.sheets[0],
        {"start_date": date(2026, 1, 1), "end_date": date(2026, 2, 1)},
    )
    assert params == [date(2026, 1, 1), date(2026, 2, 1), date(2026, 1, 1), date(2026, 2, 1)]


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
