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
