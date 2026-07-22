from datetime import date, timedelta

from demo_data import filter_demo_orders, load_demo_orders


def test_demo_data_has_expected_columns_and_rows():
    dataframe = load_demo_orders()
    assert len(dataframe) == 180
    assert list(dataframe.columns) == ["订单编号", "客户名称", "订单日期", "部门", "状态", "金额"]


def test_demo_filter_applies_date_department_and_status():
    dataframe = load_demo_orders()
    target_date = date.today() - timedelta(days=5)
    result = filter_demo_orders(
        dataframe,
        start_date=target_date,
        end_date=target_date,
        department="销售部",
        status="待处理",
    )
    assert all(result["订单日期"] == target_date)
    assert all(result["部门"] == "销售部")
    assert all(result["状态"] == "待处理")
