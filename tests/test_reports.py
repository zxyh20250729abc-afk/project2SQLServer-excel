import pytest

from reports import build_params, get_report, validate_read_only_sql


def test_build_params_keeps_user_values_as_parameters():
    params = build_params("销售部", 25, 40)
    assert params == ["销售部", "销售部", 25, 25, 40, 40]


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
    ],
)
def test_non_readonly_sql_is_rejected(sql):
    with pytest.raises(ValueError):
        validate_read_only_sql(sql)


def test_simple_select_sql_is_allowed():
    validate_read_only_sql("SELECT personid FROM dbo.employees WHERE age >= ?")
