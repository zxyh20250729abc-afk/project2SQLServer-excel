"""SQL Server 只读访问与受控查询。"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

import pandas as pd
import pyodbc

from reports import ReportDefinition, validate_report_read_only


class DatabaseConnectionError(RuntimeError):
    """数据库不可连接或认证失败时使用的安全异常。"""


class QueryExecutionError(RuntimeError):
    """查询执行失败时使用的安全异常。"""


class ReadonlyAccountError(RuntimeError):
    """当前身份不在只读白名单或拥有高权限时使用的安全异常。"""


@dataclass(frozen=True)
class PrincipalIdentity:
    login_name: str
    database_user: str
    is_sysadmin: bool
    is_db_owner: bool
    is_db_datawriter: bool


def validate_readonly_principal(identity: PrincipalIdentity, allowed_logins: Any) -> None:
    """只允许显式白名单中的低权限登录账号执行查询。"""
    if not isinstance(allowed_logins, (list, tuple)) or not allowed_logins:
        raise ReadonlyAccountError("未配置 allowed_logins，只读安全策略要求拒绝执行查询。")

    normalized_allowed = {str(login).casefold().strip() for login in allowed_logins if str(login).strip()}
    if identity.login_name.casefold().strip() not in normalized_allowed:
        raise ReadonlyAccountError("当前登录账号不在允许的只读账号名单中，已阻止查询。")

    privileged_roles = []
    if identity.is_sysadmin:
        privileged_roles.append("sysadmin")
    if identity.is_db_owner:
        privileged_roles.append("db_owner")
    if identity.is_db_datawriter:
        privileged_roles.append("db_datawriter")
    if privileged_roles:
        roles = "、".join(privileged_roles)
        raise ReadonlyAccountError(f"安全警告：当前账号具有 {roles} 高权限，已阻止查询和导出。请改用专用只读账号。")


def inspect_principal(connection: pyodbc.Connection) -> PrincipalIdentity:
    """使用只读 SELECT 检查当前 SQL Server 身份和危险角色成员资格。"""
    try:
        row = connection.cursor().execute(
            """
            SELECT
                COALESCE(ORIGINAL_LOGIN(), SYSTEM_USER) AS login_name,
                USER_NAME() AS database_user,
                IS_SRVROLEMEMBER(N'sysadmin') AS is_sysadmin,
                IS_MEMBER(N'db_owner') AS is_db_owner,
                IS_MEMBER(N'db_datawriter') AS is_db_datawriter
            """
        ).fetchone()
    except pyodbc.Error as exc:
        raise ReadonlyAccountError("无法核验当前数据库账号权限，已阻止查询。") from exc

    if not row or not row[0]:
        raise ReadonlyAccountError("无法识别当前数据库登录账号，已阻止查询。")
    return PrincipalIdentity(
        login_name=str(row[0]),
        database_user=str(row[1] or ""),
        is_sysadmin=bool(row[2]),
        is_db_owner=bool(row[3]),
        is_db_datawriter=bool(row[4]),
    )


def _as_bool(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _tcp_server(value: Any) -> str:
    """强制使用 TCP，避免客户端尝试其他 SQL Server 网络协议。"""
    server = str(value).strip()
    return server if server.casefold().startswith("tcp:") else f"tcp:{server}"


def build_connection_string(settings: Mapping[str, Any]) -> str:
    """从密钥配置构造连接串；调用方不得记录返回值，因其包含密码。"""
    required = ("server", "database", "username", "password", "driver")
    missing = [key for key in required if not settings.get(key)]
    if missing:
        raise DatabaseConnectionError(f"数据库配置缺少字段：{', '.join(missing)}")

    return (
        f"DRIVER={{{settings['driver']}}};"
        f"SERVER={_tcp_server(settings['server'])};"
        f"DATABASE={settings['database']};"
        f"UID={settings['username']};"
        f"PWD={settings['password']};"
        f"Encrypt={_as_bool(settings.get('encrypt', True))};"
        f"TrustServerCertificate={_as_bool(settings.get('trust_server_certificate', False))};"
        "ApplicationIntent=ReadOnly;"
    )


@contextmanager
def readonly_connection(settings: Mapping[str, Any]) -> Iterator[pyodbc.Connection]:
    """创建只读意图连接，并确保连接在任何异常后关闭。"""
    try:
        connection = pyodbc.connect(
            build_connection_string(settings),
            timeout=int(settings.get("connection_timeout_seconds", 15)),
            autocommit=True,
        )
        connection.timeout = int(settings.get("query_timeout_seconds", 60))
    except pyodbc.Error as exc:
        raise DatabaseConnectionError("无法连接 SQL Server，请联系管理员检查网络、账号与配置。") from exc

    try:
        validate_readonly_principal(inspect_principal(connection), settings.get("allowed_logins"))
        yield connection
    finally:
        connection.close()


def count_rows(connection: pyodbc.Connection, report: ReportDefinition, params: list[Any]) -> int:
    validate_report_read_only(report)
    try:
        row = connection.cursor().execute(report.count_sql, params).fetchone()
        return int(row[0]) if row else 0
    except pyodbc.Error as exc:
        raise QueryExecutionError("统计查询失败，请稍后重试或联系管理员。") from exc


def fetch_preview(connection: pyodbc.Connection, report: ReportDefinition, params: list[Any]) -> pd.DataFrame:
    validate_report_read_only(report)
    try:
        return pd.read_sql_query(report.preview_sql, connection, params=params)
    except Exception as exc:  # pandas 会包装 pyodbc 异常
        raise QueryExecutionError("预览查询失败，请检查筛选条件或联系管理员。") from exc


def fetch_export(connection: pyodbc.Connection, report: ReportDefinition, params: list[Any]) -> pd.DataFrame:
    validate_report_read_only(report)
    try:
        return pd.read_sql_query(report.data_sql, connection, params=params)
    except Exception as exc:
        raise QueryExecutionError("导出查询失败，请稍后重试或联系管理员。") from exc
