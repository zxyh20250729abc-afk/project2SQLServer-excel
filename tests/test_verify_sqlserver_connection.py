from reports import EMPLOYEE_REPORT, build_params
from scripts.verify_sqlserver_connection import default_filter_values


def test_employee_report_defaults_expand_age_range_without_key_error():
    filters = default_filter_values(EMPLOYEE_REPORT)

    assert filters == {"department": None, "min_age": None, "max_age": None}
    assert build_params(EMPLOYEE_REPORT.sheets[0], filters) == [None, None, None, None, None, None]
