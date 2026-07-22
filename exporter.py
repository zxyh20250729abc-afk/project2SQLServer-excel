"""Excel 文件生成。"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
import re

import pandas as pd


def create_filename(report_name: str) -> str:
    """生成可追溯且不包含不安全文件名字符的导出文件名。"""
    safe_name = re.sub(r'[\\/:*?"<>|]+', "_", report_name).strip() or "report"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{safe_name}_{timestamp}.xlsx"


def dataframe_to_excel(dataframe: pd.DataFrame, sheet_name: str = "数据明细") -> bytes:
    """输出包含筛选、冻结首行和安全列宽的 xlsx 内容。"""
    buffer = BytesIO()
    safe_sheet_name = re.sub(r'[:\\/?*\[\]]', "_", sheet_name)[:31] or "数据明细"

    with pd.ExcelWriter(buffer, engine="xlsxwriter", datetime_format="yyyy-mm-dd hh:mm:ss", date_format="yyyy-mm-dd") as writer:
        dataframe.to_excel(writer, sheet_name=safe_sheet_name, index=False)
        workbook = writer.book
        worksheet = writer.sheets[safe_sheet_name]
        header_format = workbook.add_format({"bold": True, "bg_color": "#1F4D78", "font_color": "#FFFFFF", "border": 1})
        worksheet.freeze_panes(1, 0)
        worksheet.autofilter(0, 0, len(dataframe), max(len(dataframe.columns) - 1, 0))

        for index, column in enumerate(dataframe.columns):
            series = dataframe[column].astype(str) if not dataframe.empty else pd.Series([str(column)])
            max_len = max(len(str(column)), int(series.map(len).max()))
            worksheet.set_column(index, index, min(max(max_len + 2, 10), 40))
            worksheet.write(0, index, column, header_format)

    return buffer.getvalue()
