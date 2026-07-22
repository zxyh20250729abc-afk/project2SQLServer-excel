from demo_data import load_demo_employees
from discovery import discover_demo_employee_filters, discover_employee_filters


class FakeCursor:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        self._result = self.results[len(self.calls) - 1]
        return self

    def fetchall(self):
        return self._result


class FakeConnection:
    def __init__(self, results):
        self.cursor_instance = FakeCursor(results)

    def cursor(self):
        return self.cursor_instance


def test_demo_discovery_uses_only_approved_employee_filters():
    filters = discover_demo_employee_filters(load_demo_employees())
    assert [item.key for item in filters] == ["department", "age"]
    assert "销售部" in filters[0].options
    assert filters[1].kind == "integer_range"


def test_sqlserver_discovery_uses_fixed_parameterized_metadata_query():
    connection = FakeConnection(
        [
            [("personid", "int"), ("department", "varchar"), ("age", "int"), ("salary", "decimal")],
            [("市场部",), ("销售部",)],
        ]
    )

    filters = discover_employee_filters(connection)

    assert [item.key for item in filters] == ["department", "age"]
    assert filters[0].options == ("市场部", "销售部")
    metadata_sql, metadata_params = connection.cursor_instance.calls[0]
    assert metadata_sql.lstrip().upper().startswith("SELECT")
    assert metadata_params == ["dbo", "employees"]
    assert connection.cursor_instance.calls[1][0].lstrip().upper().startswith("SELECT")
