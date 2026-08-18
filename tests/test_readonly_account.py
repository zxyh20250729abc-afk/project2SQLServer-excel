import pytest

from database import PrincipalIdentity, ReadonlyAccountError, build_connection_string, validate_readonly_principal


def make_identity(**overrides):
    values = {
        "login_name": "report_export_reader",
        "database_user": "report_export_reader",
        "is_sysadmin": False,
        "is_db_owner": False,
        "is_db_datawriter": False,
    }
    values.update(overrides)
    return PrincipalIdentity(**values)


def test_approved_low_privilege_account_is_allowed():
    validate_readonly_principal(make_identity(), ["report_export_reader"])


def test_unlisted_account_is_blocked():
    with pytest.raises(ReadonlyAccountError, match="不在允许"):
        validate_readonly_principal(make_identity(login_name="shared_user"), ["report_export_reader"])


@pytest.mark.parametrize("role", ["is_sysadmin", "is_db_owner", "is_db_datawriter"])
def test_high_privilege_account_is_blocked_even_if_allowlisted(role):
    with pytest.raises(ReadonlyAccountError, match="高权限"):
        validate_readonly_principal(make_identity(**{role: True}), ["report_export_reader"])


def test_empty_allowlist_fails_closed():
    with pytest.raises(ReadonlyAccountError, match="未配置"):
        validate_readonly_principal(make_identity(), [])


def test_connection_string_forces_tcp_without_exposing_password():
    connection_string = build_connection_string(
        {
            "server": "192.0.2.19,1433",
            "database": "db_test0",
            "username": "report_export_reader",
            "password": "example-secret",
            "driver": "ODBC Driver 18 for SQL Server",
        }
    )
    assert "SERVER={tcp:192.0.2.19,1433};" in connection_string


def test_connection_string_escapes_special_characters_in_password():
    connection_string = build_connection_string(
        {
            "server": "192.0.2.19,1433",
            "database": "ekp_dyy_test",
            "username": "report_export_reader",
            "password": "secret;with}characters",
            "driver": "ODBC Driver 17 for SQL Server",
        }
    )
    assert "PWD={secret;with}}characters};" in connection_string
