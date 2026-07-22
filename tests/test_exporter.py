from datetime import date

import pandas as pd

from exporter import create_filename, dataframe_to_excel


def test_filename_is_xlsx_and_does_not_keep_illegal_characters():
    filename = create_filename('销售/明细:*?', date(2026, 7, 1), date(2026, 7, 2))
    assert filename.endswith('.xlsx')
    assert '/' not in filename and ':' not in filename and '*' not in filename and '?' not in filename


def test_dataframe_to_excel_returns_non_empty_xlsx_bytes():
    content = dataframe_to_excel(pd.DataFrame({'订单编号': ['A001'], '金额': [12.5]}))
    assert len(content) > 1000
    assert content[:2] == b'PK'
