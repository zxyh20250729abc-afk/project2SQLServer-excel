"""Excel 文件生成。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from io import BytesIO
import re

import pandas as pd


def create_filename(report_name: str) -> str:
    """生成可追溯且不包含不安全文件名字符的导出文件名。"""
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", report_name).strip() or "report"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe_name}_{timestamp}.xlsx"


def _safe_sheet_name(value: str, used_names: set[str]) -> str:
    """将任意工作表名转换为 Excel 可接受且不重复的名称。"""
    base_name = re.sub(r'[:\\/?*\[\]]', "_", value).strip()[:31] or "数据明细"
    candidate = base_name
    sequence = 2
    while candidate.casefold() in used_names:
        suffix = f"_{sequence}"
        candidate = f"{base_name[: 31 - len(suffix)]}{suffix}"
        sequence += 1
    used_names.add(candidate.casefold())
    return candidate


def dataframes_to_excel(dataframes: Mapping[str, pd.DataFrame]) -> bytes:
    """输出多工作表 Excel；每张表均包含冻结表头、筛选和安全列宽。"""
    if not dataframes:
        raise ValueError("至少需要一个工作表数据。")

    buffer = BytesIO()

    with pd.ExcelWriter(buffer, engine="xlsxwriter", datetime_format="yyyy-mm-dd hh:mm:ss", date_format="yyyy-mm-dd") as writer:
        workbook = writer.book
        header_format = workbook.add_format({"bold": True, "bg_color": "#1F4D78", "font_color": "#FFFFFF", "border": 1})
        used_names: set[str] = set()
        for requested_name, dataframe in dataframes.items():
            safe_sheet_name = _safe_sheet_name(str(requested_name), used_names)
            dataframe.to_excel(writer, sheet_name=safe_sheet_name, index=False)
            worksheet = writer.sheets[safe_sheet_name]
            worksheet.freeze_panes(1, 0)
            worksheet.autofilter(0, 0, len(dataframe), max(len(dataframe.columns) - 1, 0))

            for index, column in enumerate(dataframe.columns):
                series = dataframe[column].astype(str) if not dataframe.empty else pd.Series([str(column)])
                max_len = max(len(str(column)), int(series.map(len).max()))
                worksheet.set_column(index, index, min(max(max_len + 2, 10), 40))
                worksheet.write(0, index, column, header_format)

    return buffer.getvalue()


def dataframe_to_excel(dataframe: pd.DataFrame, sheet_name: str = "数据明细") -> bytes:
    """保留单工作表调用方式，兼容现有代码。"""
    return dataframes_to_excel({sheet_name: dataframe})
