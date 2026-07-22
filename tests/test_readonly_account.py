import pytest

from database import PrincipalIdentity, ReadonlyAccountError, validate_readonly_principal


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
