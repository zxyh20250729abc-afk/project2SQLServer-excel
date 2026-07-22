import pandas as pd

from exporter import create_filename, dataframe_to_excel


def test_filename_is_xlsx_and_does_not_keep_illegal_characters():
    filename = create_filename('员工/明细:*?')
    assert filename.endswith('.xlsx')
    assert '/' not in filename and ':' not in filename and '*' not in filename and '?' not in filename


def test_dataframe_to_excel_returns_non_empty_xlsx_bytes():
    content = dataframe_to_excel(pd.DataFrame({'人员编号': [1], '薪资': [12.5]}))
    assert len(content) > 1000
    assert content[:2] == b'PK'
