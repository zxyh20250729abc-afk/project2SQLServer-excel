from datetime import date

from audit import list_saved_queries, save_query


def test_saved_query_keeps_only_conditions_and_selected_fields(tmp_path):
    db_path = tmp_path / "audit.db"
    save_query(
        str(db_path),
        operator_id="行政小王",
        query_name="本月发票核对",
        dataset_key="finance_expense_invoice",
        filters={"year": 2026, "start_date": date(2026, 8, 1)},
        selected_fields=["部门", "价税合计"],
    )

    saved = list_saved_queries(str(db_path), operator_id="行政小王")

    assert len(saved) == 1
    assert saved[0]["query_name"] == "本月发票核对"
    assert saved[0]["filters"]["start_date"] == "2026-08-01"
    assert saved[0]["selected_fields"] == ["部门", "价税合计"]


def test_saved_query_with_same_name_updates_instead_of_duplicating(tmp_path):
    db_path = tmp_path / "audit.db"
    for year in (2025, 2026):
        save_query(
            str(db_path),
            operator_id="1001",
            query_name="年度合同金额",
            dataset_key="contract_amount_summary",
            filters={"year": year},
            selected_fields=["合同金额"],
        )

    saved = list_saved_queries(str(db_path), operator_id="1001")

    assert len(saved) == 1
    assert saved[0]["filters"] == {"year": 2026}
