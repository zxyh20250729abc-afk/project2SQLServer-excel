from catalog import available_datasets, get_dataset, search_datasets


def test_business_catalog_uses_user_facing_topics_instead_of_table_names():
    dataset = get_dataset("finance_expense_invoice")

    assert dataset.domain_name == "财务数据"
    assert dataset.title == "查询报销发票"
    assert "mod_fi_expense" not in dataset.description
    assert any(field.label == "价税合计" and field.recommended for field in dataset.fields)


def test_catalog_search_matches_business_words():
    matched = search_datasets(available_datasets("sqlserver"), "发票")

    assert [dataset.report_key for dataset in matched] == ["finance_expense_invoice"]


def test_demo_mode_only_offers_test_dataset():
    datasets = available_datasets("demo")

    assert [dataset.report_key for dataset in datasets] == ["employee_list"]
