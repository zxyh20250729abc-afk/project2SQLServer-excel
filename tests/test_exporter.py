from io import BytesIO
import zipfile

import pandas as pd

from exporter import create_filename, dataframe_to_excel, dataframes_to_excel


def test_filename_is_xlsx_and_does_not_keep_illegal_characters():
    filename = create_filename('员工/明细:*?')
    assert filename.endswith('.xlsx')
    assert '/' not in filename and ':' not in filename and '*' not in filename and '?' not in filename


def test_dataframe_to_excel_returns_non_empty_xlsx_bytes():
    content = dataframe_to_excel(pd.DataFrame({'人员编号': [1], '薪资': [12.5]}))
    assert len(content) > 1000
    assert content[:2] == b'PK'


def test_dataframes_to_excel_keeps_multiple_worksheets():
    content = dataframes_to_excel(
        {
            "主合同": pd.DataFrame({"合同编号": ["A001"]}),
            "终止合同": pd.DataFrame({"合同编号": ["B001"]}),
        }
    )
    with zipfile.ZipFile(BytesIO(content)) as workbook:
        sheet_xml = workbook.read("xl/workbook.xml").decode("utf-8")
    assert "主合同" in sheet_xml
    assert "终止合同" in sheet_xml
