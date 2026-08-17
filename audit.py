"""本地导出审计日志。日志只保存操作元数据，不保存数据库凭据和结果明细。"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


def initialize(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS export_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_utc TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                report_key TEXT NOT NULL,
                filters_json TEXT NOT NULL,
                row_count INTEGER,
                status TEXT NOT NULL CHECK (status IN ('success', 'failure')),
                error_summary TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS saved_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at_utc TEXT NOT NULL,
                operator_id TEXT NOT NULL,
                query_name TEXT NOT NULL,
                dataset_key TEXT NOT NULL,
                filters_json TEXT NOT NULL,
                fields_json TEXT NOT NULL,
                UNIQUE(operator_id, query_name)
            )
            """
        )


def record(
    db_path: str,
    *,
    operator_id: str,
    report_key: str,
    filters: dict[str, Any],
    status: str,
    row_count: int | None = None,
    error_summary: str | None = None,
) -> None:
    """写入审计记录；错误摘要由调用方脱敏后传入。"""
    initialize(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO export_audit
              (created_at_utc, operator_id, report_key, filters_json, row_count, status, error_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                operator_id.strip()[:100],
                report_key,
                json.dumps(filters, ensure_ascii=False, default=str),
                row_count,
                status,
                (error_summary or "")[:500] or None,
            ),
        )


def save_query(
    db_path: str,
    *,
    operator_id: str,
    query_name: str,
    dataset_key: str,
    filters: dict[str, Any],
    selected_fields: list[str],
) -> None:
    """保存常用查询条件；只保存元数据，不保存导出结果或数据库凭据。"""
    normalized_operator = operator_id.strip()[:100]
    normalized_name = query_name.strip()[:100]
    if not normalized_operator:
        raise ValueError("请输入姓名或工号后再保存常用查询。")
    if not normalized_name:
        raise ValueError("请为常用查询填写名称。")
    if not dataset_key:
        raise ValueError("缺少业务查询事项。")

    initialize(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO saved_queries
              (created_at_utc, operator_id, query_name, dataset_key, filters_json, fields_json)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(operator_id, query_name) DO UPDATE SET
              created_at_utc = excluded.created_at_utc,
              dataset_key = excluded.dataset_key,
              filters_json = excluded.filters_json,
              fields_json = excluded.fields_json
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                normalized_operator,
                normalized_name,
                dataset_key,
                json.dumps(filters, ensure_ascii=False, default=str),
                json.dumps(selected_fields, ensure_ascii=False),
            ),
        )


def list_saved_queries(db_path: str, *, operator_id: str, limit: int = 8) -> list[dict[str, Any]]:
    """读取当前操作人的常用查询；损坏记录会被安全忽略。"""
    normalized_operator = operator_id.strip()[:100]
    if not normalized_operator or not Path(db_path).exists():
        return []
    initialize(db_path)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT query_name, dataset_key, filters_json, fields_json
            FROM saved_queries
            WHERE operator_id = ?
            ORDER BY created_at_utc DESC
            LIMIT ?
            """,
            (normalized_operator, max(1, min(int(limit), 50))),
        ).fetchall()

    saved: list[dict[str, Any]] = []
    for query_name, dataset_key, filters_json, fields_json in rows:
        try:
            filters = json.loads(filters_json)
            fields = json.loads(fields_json)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(filters, dict) and isinstance(fields, list):
            saved.append(
                {
                    "query_name": str(query_name),
                    "dataset_key": str(dataset_key),
                    "filters": filters,
                    "selected_fields": [str(field) for field in fields],
                }
            )
    return saved
