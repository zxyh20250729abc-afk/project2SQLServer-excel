"""经批准的只读报表定义。

业务人员只能在页面选择预设报表和参数。所有 SQL 均在本文件中版本管理，
并使用 ``?`` 参数绑定；页面不会接收或拼接任意 SQL。
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Mapping


@dataclass(frozen=True)
class FilterDefinition:
    """经批准、可在页面展示的筛选控件。"""

    key: str
    column_name: str
    label: str
    kind: str  # enum、integer_range、integer、month 或 date
    required: bool = False
    minimum: int | None = None
    maximum: int | None = None


@dataclass(frozen=True)
class ReportSheet:
    """一个 Excel 工作表对应的一条固定只读查询。"""

    name: str
    data_sql: str
    preview_sql: str
    count_sql: str
    parameter_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReportDefinition:
    key: str
    name: str
    description: str
    source_note: str
    filters: tuple[FilterDefinition, ...]
    sheets: tuple[ReportSheet, ...]
    supports_demo: bool = False


def _sheet(
    name: str,
    base_sql: str,
    *,
    parameter_keys: tuple[str, ...] = (),
    order_by: str | None = None,
) -> ReportSheet:
    """以同一固定基础查询生成导出、预览和计数 SQL。"""
    normalized_base = base_sql.strip()
    order_clause = f"\nORDER BY {order_by}" if order_by else ""
    return ReportSheet(
        name=name,
        data_sql=normalized_base + order_clause,
        preview_sql=f"SELECT TOP (100) * FROM (\n{normalized_base}\n) AS report_preview" + order_clause,
        count_sql=f"SELECT COUNT_BIG(1) AS row_count FROM (\n{normalized_base}\n) AS report_count",
        parameter_keys=parameter_keys,
    )


# 模拟/连通性验证用的测试报表。生产环境使用下方的真实业务报表。
_EMPLOYEE_BASE = """
SELECT
    personid AS [人员编号],
    lastname AS [姓],
    firstname AS [名],
    age AS [年龄],
    department AS [部门],
    salary AS [薪资]
FROM dbo.employees
WHERE (? IS NULL OR department = ?)
  AND (? IS NULL OR age >= ?)
  AND (? IS NULL OR age <= ?)
"""

EMPLOYEE_FILTERS = (
    FilterDefinition(key="department", column_name="department", label="部门", kind="enum"),
    FilterDefinition(key="age", column_name="age", label="年龄", kind="integer_range", minimum=0, maximum=150),
)

EMPLOYEE_REPORT = ReportDefinition(
    key="employee_list",
    name="员工信息（测试）",
    description="用于验证连接、筛选和 Excel 导出流程的测试报表。",
    source_note="数据源：dbo.employees（仅用于测试；真实业务请使用下方预设报表）。",
    filters=EMPLOYEE_FILTERS,
    sheets=(
        _sheet(
            "员工信息",
            _EMPLOYEE_BASE,
            parameter_keys=("department", "department", "min_age", "min_age", "max_age", "max_age"),
            order_by="[人员编号] ASC",
        ),
    ),
    supports_demo=True,
)


_YEAR_MONTH_FILTERS = (
    FilterDefinition(key="year", column_name="", label="用友记账年份", kind="integer", required=True, minimum=2000, maximum=2100),
    FilterDefinition(key="start_month", column_name="", label="起始月份", kind="month", required=True, minimum=1, maximum=12),
    FilterDefinition(key="end_month", column_name="", label="结束月份", kind="month", required=True, minimum=1, maximum=12),
)

_INVOICE_FILTERS = (
    FilterDefinition(key="year", column_name="", label="用友记账年份", kind="integer", required=True, minimum=2000, maximum=2100),
    FilterDefinition(key="start_month", column_name="", label="起始月份", kind="month", required=True, minimum=1, maximum=12),
)

_DATE_RANGE_FILTERS = (
    FilterDefinition(key="start_date", column_name="", label="开始日期（含）", kind="date", required=True),
    FilterDefinition(key="end_date", column_name="", label="结束日期（不含）", kind="date", required=True),
)


# 以下报表根据“数据统计SQL”目录中提供的脚本整理而来。
# 变量赋值语句已替换为参数绑定；原脚本的多个结果集会导出到同一个 Excel 的不同工作表。
_CLAIM_DETAIL_BASE = """
SELECT
    (SELECT fd_name FROM sys_org_element AS T2 WHERE T2.fd_id = Y1.doc_creator_id) AS [申请人],
    (SELECT fd_name FROM sys_org_element AS T2 WHERE T2.fd_id = Y1.fd_dept_id) AS [申请部门],
    doc_create_time AS [申请时间],
    doc_number AS [认款单编号],
    fd_nc_owner AS [认款单位],
    fd_contract_code AS [合同编号],
    fd_project_name AS [项目名称],
    (SELECT fd_owner_unit FROM mod_contract_main AS T2 WHERE T2.fd_id = Y1.fd_contract_id) AS [业主单位],
    (SELECT fd_contract_money FROM mod_contract_main AS T2 WHERE T2.fd_id = Y1.fd_contract_id) AS [合同金额],
    fd_project_no AS [核算编号],
    fd_total_amount AS [认款金额],
    fd_manage_amount AS [管理费],
    (SELECT fd_name FROM mod_base_source_fund WHERE fd_id = Y1.fd_amount_source_id) AS [资金来源],
    (SELECT fd_name FROM mod_base_con_type WHERE fd_id = Y1.fd_bus_type_id) AS [业务类型],
    fd_buyer_name AS [付款方],
    fd_nc_year + '-' + fd_nc_month AS [用友记账年月],
    fd_nc_billno AS [用友记账号]
FROM mod_fi_claim AS Y1
WHERE doc_status = 30
  AND fd_nc_year = ?
  AND CONVERT(int, fd_nc_month) BETWEEN ? AND ?
"""

CLAIM_DETAIL_REPORT = ReportDefinition(
    key="finance_claim_detail",
    name="财务－认款明细统计",
    description="按用友记账年份和月份区间导出认款单明细。",
    source_note="数据源：mod_fi_claim、mod_contract_main 等已批准业务表。",
    filters=_YEAR_MONTH_FILTERS,
    sheets=(_sheet("认款明细", _CLAIM_DETAIL_BASE, parameter_keys=("year", "start_month", "end_month"), order_by="[申请部门], [申请时间]"),),
)

_CLAIM_AMOUNT_BASE = """
SELECT
    T.[申请部门],
    T.[用友记账年月],
    ROUND(SUM(T.[认款金额]), 2) AS [认款金额],
    ROUND(SUM(T.[管理费]), 2) AS [管理费]
FROM (
    SELECT
        (SELECT fd_name FROM sys_org_element AS T2 WHERE T2.fd_id = Y1.fd_dept_id) AS [申请部门],
        fd_total_amount AS [认款金额],
        fd_manage_amount AS [管理费],
        fd_nc_year + '-' + fd_nc_month AS [用友记账年月]
    FROM mod_fi_claim AS Y1
    WHERE doc_status = 30
      AND fd_nc_year = ?
      AND CONVERT(int, fd_nc_month) BETWEEN ? AND ?
) AS T
GROUP BY T.[申请部门], T.[用友记账年月]
"""

CLAIM_AMOUNT_REPORT = ReportDefinition(
    key="finance_claim_amount",
    name="财务－认款金额统计",
    description="按部门和用友记账月份汇总认款金额、管理费。",
    source_note="数据源：mod_fi_claim、sys_org_element。",
    filters=_YEAR_MONTH_FILTERS,
    sheets=(_sheet("认款金额汇总", _CLAIM_AMOUNT_BASE, parameter_keys=("year", "start_month", "end_month"), order_by="[申请部门], [用友记账年月]"),),
)

_EXPENSE_INVOICE_BASE = """
SELECT
    (SELECT fd_name FROM sys_org_element WHERE fd_id = T1.fd_dept_id) AS [部门],
    doc_number AS [报销单号],
    fd_nc_billno AS [用友凭证号],
    T1.fd_nc_year AS [用友记账年份],
    T1.fd_nc_month AS [用友记账月份],
    T2.fd_invoice_type AS [发票类型],
    T2.fd_invoice_code AS [发票代码],
    T2.fd_invoice_number AS [发票号码],
    T2.fd_invoice_date AS [开票日期],
    T2.fd_tax AS [税率],
    T2.fd_invoice_money AS [价税合计],
    T2.fd_no_tax_money AS [不含税金额],
    T2.fd_tax_money AS [税额],
    CASE WHEN fd_check_status = 1 THEN '已验真' ELSE '未验真' END AS [验真状态],
    fd_check_code AS [校验码],
    fd_tax_number AS [购方税号],
    fd_purch_name AS [购方名称],
    fd_seller_name AS [销售方]
FROM mod_fi_expense AS T1
INNER JOIN mod_fi_invoice_detail AS T2 ON T1.fd_id = T2.doc_main_id
WHERE fd_nc_year = ?
  AND CONVERT(int, fd_nc_month) >= ?
  AND fd_nc_billno IS NOT NULL
  AND doc_status > 10
"""

EXPENSE_INVOICE_REPORT = ReportDefinition(
    key="finance_expense_invoice",
    name="财务－报销发票统计",
    description="按用友记账年份和起始月份导出已入账报销发票。",
    source_note="数据源：mod_fi_expense、mod_fi_invoice_detail。",
    filters=_INVOICE_FILTERS,
    sheets=(_sheet("报销发票", _EXPENSE_INVOICE_BASE, parameter_keys=("year", "start_month"), order_by="[部门], [报销单号]"),),
)

_CONTRACT_AMOUNT_SUMMARY_BASE = """
SELECT
    last_tab.[部门名称] AS [部门],
    last_tab.[合同备案时间] AS [合同备案时间],
    last_tab.[合同金额] - ISNULL(terminated.[终止金额], 0) AS [合同金额]
FROM (
    SELECT [部门名称], [合同备案时间], SUM([金额]) AS [合同金额]
    FROM (
        SELECT
            [部门名称],
            ISNULL(CASE WHEN [合同类型] = 4 THEN [补充调整金额] ELSE [合同金额] END, 0) AS [金额],
            [合同备案时间]
        FROM (
            SELECT
                S.fd_name AS [部门名称],
                C.fd_contract_properties AS [合同类型],
                C.fd_contract_money AS [合同金额],
                CASE WHEN C.fd_adjust_way = 2 THEN C.fd_adjust_money * -1 ELSE C.fd_adjust_money END AS [补充调整金额],
                FORMAT(C.fd_contract_reg_date, 'yyyy-MM') AS [合同备案时间]
            FROM mod_contract_main AS C
            LEFT JOIN sys_org_element AS S ON C.doc_dept_id = S.fd_id
            WHERE C.fd_contract_reg_date >= ?
              AND C.fd_contract_reg_date < ?
              AND (C.fd_contract_properties IN (2, 4)
                   OR (C.fd_contract_properties = 1 AND C.fd_has_main_contract IS NULL AND C.fd_main_contract_id IS NULL))
              AND C.fd_record_reg_no NOT LIKE '%TEST%'
              AND C.fd_record_reg_no NOT LIKE '%外%'
        ) AS contracts
    ) AS contract_amounts
    GROUP BY [部门名称], [合同备案时间]
) AS last_tab
LEFT JOIN (
    SELECT [部门名称], [终止协议签订时间], SUM([终止合同金额]) AS [终止金额]
    FROM (
        SELECT
            S.fd_name AS [部门名称],
            T1.fd_contract_money AS [终止合同金额],
            FORMAT(T.fd_sign_date, 'yyyy-MM') AS [终止协议签订时间]
        FROM mod_contract_close AS T
        LEFT JOIN sys_org_element AS S ON T.doc_dept_id = S.fd_id
        INNER JOIN mod_contract_main AS T1 ON T.fd_contract_id = T1.fd_id
        WHERE T.fd_sign_date >= ?
          AND T.fd_sign_date < ?
          AND T1.fd_record_reg_no NOT LIKE '%TEST%'
          AND T1.fd_contract_properties IN (1, 2, 4)
          AND T.doc_status = 30
    ) AS terminated_contracts
    GROUP BY [部门名称], [终止协议签订时间]
) AS terminated
  ON last_tab.[合同备案时间] = terminated.[终止协议签订时间]
 AND last_tab.[部门名称] = terminated.[部门名称]
"""

CONTRACT_AMOUNT_SUMMARY_REPORT = ReportDefinition(
    key="contract_amount_summary",
    name="合同－合同金额统计",
    description="统计主合同、补充协议，并统筹扣减终止合同金额。",
    source_note="数据源：mod_contract_main、mod_contract_close、sys_org_element。",
    filters=_DATE_RANGE_FILTERS,
    sheets=(_sheet("合同金额汇总", _CONTRACT_AMOUNT_SUMMARY_BASE, parameter_keys=("start_date", "end_date", "start_date", "end_date"), order_by="[部门], [合同备案时间]"),),
)

_CONTRACT_DETAIL_BASE = """
SELECT
    [部门名称],
    [合同编号],
    ISNULL(CASE WHEN [合同类型代码] = 4 THEN [补充调整金额] ELSE [合同金额] END, 0) AS [合同金额],
    [合同备案时间],
    CASE
        WHEN [合同类型代码] = 1 THEN '特殊合同'
        WHEN [合同类型代码] = 2 THEN '主合同'
        WHEN [合同类型代码] = 3 THEN '采购合同'
        WHEN [合同类型代码] = 4 THEN '补充协议'
    END AS [合同类型]
FROM (
    SELECT
        S.fd_name AS [部门名称],
        C.fd_record_reg_no AS [合同编号],
        C.fd_contract_properties AS [合同类型代码],
        C.fd_contract_money AS [合同金额],
        CASE WHEN C.fd_adjust_way = 2 THEN C.fd_adjust_money * -1 ELSE C.fd_adjust_money END AS [补充调整金额],
        FORMAT(C.fd_contract_reg_date, 'yyyy-MM') AS [合同备案时间]
    FROM mod_contract_main AS C
    LEFT JOIN sys_org_element AS S ON C.doc_dept_id = S.fd_id
    WHERE C.fd_contract_reg_date >= ?
      AND C.fd_contract_reg_date < ?
      AND (C.fd_contract_properties IN (2, 4)
           OR (C.fd_contract_properties = 1 AND C.fd_has_main_contract IS NULL AND C.fd_main_contract_id IS NULL))
      AND C.fd_record_reg_no NOT LIKE '%TEST%'
      AND C.fd_record_reg_no NOT LIKE '%外%'
) AS contracts
"""

_TERMINATED_CONTRACT_DETAIL_BASE = """
SELECT
    S.fd_name AS [部门名称],
    T.fd_close_contract_reg_no AS [合同编号],
    T1.fd_contract_money AS [终止合同金额],
    FORMAT(T.fd_sign_date, 'yyyy-MM') AS [终止协议签订时间]
FROM mod_contract_close AS T
LEFT JOIN sys_org_element AS S ON T.doc_dept_id = S.fd_id
INNER JOIN mod_contract_main AS T1 ON T.fd_contract_id = T1.fd_id
WHERE T.fd_sign_date >= ?
  AND T.fd_sign_date < ?
  AND T1.fd_record_reg_no NOT LIKE '%TEST%'
  AND T1.fd_contract_properties IN (1, 2, 4)
  AND T.doc_status = 30
"""

CONTRACT_AMOUNT_DETAIL_REPORT = ReportDefinition(
    key="contract_amount_detail",
    name="合同－合同金额统计明细",
    description="分别导出主合同/补充协议明细和终止合同明细。",
    source_note="数据源：mod_contract_main、mod_contract_close、sys_org_element。",
    filters=_DATE_RANGE_FILTERS,
    sheets=(
        _sheet("主合同及补充协议", _CONTRACT_DETAIL_BASE, parameter_keys=("start_date", "end_date"), order_by="[部门名称], [合同备案时间]"),
        _sheet("终止合同", _TERMINATED_CONTRACT_DETAIL_BASE, parameter_keys=("start_date", "end_date"), order_by="[部门名称], [终止协议签订时间]"),
    ),
)

_STAMP_MAIN_BASE = """
SELECT
    '重庆地质矿产研究院' AS [签订单位],
    S.fd_name AS [部门名称],
    C.fd_record_reg_no AS [合同编号],
    C.doc_subject AS [合同名称],
    (SELECT fd_name FROM mod_base_grade_cate WHERE fd_code = C.fd_grade_type_code) AS [合同类别],
    (SELECT fd_name FROM mod_base_price_fix WHERE fd_id = C.fd_contract_price_id) AS [合同定价类型],
    FORMAT(C.fd_contract_reg_date, 'yyyy-MM-dd') AS [合同备案时间],
    C.fd_contract_money AS [合同金额],
    CASE WHEN C.fd_contract_text_sure_amount = 1 THEN '是' ELSE '否' END AS [是否约定金额]
FROM mod_contract_main AS C
LEFT JOIN sys_org_element AS S ON C.doc_dept_id = S.fd_id
WHERE C.fd_contract_reg_date >= ?
  AND C.fd_contract_reg_date < ?
  AND C.fd_contract_properties IN (2)
  AND C.fd_record_reg_no NOT LIKE '%TEST%'
  AND C.fd_record_reg_no NOT LIKE '%外%'
  AND C.fd_record_reg_no NOT LIKE '%D地学%'
  AND C.fd_record_reg_no NOT LIKE '%未签合同%'
"""

_STAMP_PURCHASE_BASE = """
SELECT
    '重庆地质矿产研究院' AS [签订单位],
    S.fd_name AS [部门名称],
    C.fd_record_reg_no AS [合同编号],
    C.doc_subject AS [合同名称],
    (SELECT fd_name FROM mod_base_con_cglx WHERE fd_id = C.fd_purch_contract_type_id) AS [采购合同类别],
    (SELECT fd_name FROM mod_base_price_fix WHERE fd_id = C.fd_contract_price_id) AS [合同定价类型],
    C.fd_sign_date AS [合同签订时间],
    FORMAT(C.fd_contract_reg_date, 'yyyy-MM-dd') AS [合同备案时间],
    C.fd_contract_money AS [合同金额],
    CASE WHEN C.fd_contract_text_sure_amount = 1 THEN '是' ELSE '否' END AS [是否约定金额]
FROM mod_contract_main AS C
LEFT JOIN sys_org_element AS S ON C.doc_dept_id = S.fd_id
WHERE C.fd_sign_date >= ?
  AND C.fd_sign_date < ?
  AND C.fd_contract_properties IN (3)
  AND C.fd_record_reg_no NOT LIKE '%TEST%'
  AND C.fd_record_reg_no NOT LIKE '%D地学%'
  AND C.fd_record_reg_no NOT LIKE '%未签合同%'
"""

_STAMP_INCOME_SETTLEMENT_BASE = """
SELECT
    '重庆地质矿产研究院' AS [签订单位],
    (SELECT fd_name FROM sys_org_element AS org WHERE org.fd_id = T1.fd_dept_id) AS [申请部门],
    T3.fd_record_reg_no AS [合同编号],
    T1.fd_contract_name AS [合同名称],
    (SELECT fd_name FROM mod_base_grade_cate WHERE fd_code = T3.fd_grade_type_code) AS [合同类别],
    (SELECT fd_name FROM mod_base_price_fix WHERE fd_id = T3.fd_contract_price_id) AS [合同定价类型],
    T3.fd_contract_money AS [合同金额],
    T3.fd_contract_reg_date AS [合同备案日期],
    T2.fd_create_time AS [结算日期],
    T1.fd_settle_amount AS [结算金额],
    CASE WHEN T3.fd_contract_text_sure_amount = 1 THEN '是' ELSE '否' END AS [是否约定金额]
FROM mod_settle_recon AS T1
LEFT JOIN (SELECT * FROM lbpm_audit_note WHERE fd_fact_node_name = '结束节点') AS T2 ON T1.fd_id = T2.fd_process_id
LEFT JOIN mod_contract_main AS T3 ON T1.fd_contract_id = T3.fd_id
WHERE T1.doc_status = 30
  AND T2.fd_create_time >= ?
  AND T2.fd_create_time < ?
"""

_STAMP_EXPENSE_SETTLEMENT_BASE = """
SELECT
    '重庆地质矿产研究院' AS [签订单位],
    (SELECT fd_name FROM sys_org_element AS org WHERE org.fd_id = T1.fd_dept_id) AS [申请部门],
    T3.fd_record_reg_no AS [合同编号],
    T1.fd_contract_name AS [合同名称],
    (SELECT fd_name FROM mod_base_grade_cate WHERE fd_code = T3.fd_grade_type_code) AS [合同类别],
    (SELECT fd_name FROM mod_base_price_fix WHERE fd_id = T3.fd_contract_price_id) AS [合同定价类型],
    T3.fd_contract_money AS [合同金额],
    T3.fd_contract_reg_date AS [合同备案日期],
    T2.fd_create_time AS [结算日期],
    T1.fd_settle_amount AS [结算金额],
    CASE WHEN T3.fd_contract_text_sure_amount = 1 THEN '是' ELSE '否' END AS [是否约定金额]
FROM mod_settle_pacon AS T1
LEFT JOIN (SELECT * FROM lbpm_audit_note WHERE fd_fact_node_name = '结束节点') AS T2 ON T1.fd_id = T2.fd_process_id
LEFT JOIN mod_contract_main AS T3 ON T1.fd_contract_id = T3.fd_id
WHERE T1.doc_status = 30
  AND T2.fd_create_time >= ?
  AND T2.fd_create_time < ?
"""

_STAMP_REIMBURSEMENT_BASE = """
SELECT
    '重庆地质矿产研究院' AS [签订单位],
    (SELECT fd_name FROM sys_org_element AS org WHERE org.fd_id = T1.fd_dept_id) AS [申请部门],
    T3.fd_record_reg_no AS [合同编号],
    T3.doc_subject AS [合同名称],
    (SELECT fd_name FROM mod_base_grade_cate WHERE fd_code = T3.fd_grade_type_code) AS [合同类别],
    (SELECT fd_name FROM mod_base_price_fix WHERE fd_id = T3.fd_contract_price_id) AS [合同定价类型],
    T3.fd_contract_money AS [合同金额],
    T3.fd_contract_reg_date AS [合同备案日期],
    T2.fd_create_time AS [结算日期],
    T1.fd_pay_settle_amount AS [结算金额],
    CASE WHEN T3.fd_contract_text_sure_amount = 1 THEN '是' ELSE '否' END AS [是否约定金额]
FROM mod_fi_expense AS T1
LEFT JOIN (SELECT * FROM lbpm_audit_note WHERE fd_fact_node_name = '结束节点') AS T2 ON T1.fd_id = T2.fd_process_id
LEFT JOIN mod_contract_main AS T3 ON T1.fd_pay_contract_id = T3.fd_id
WHERE T1.doc_status = 30
  AND T2.fd_create_time >= ?
  AND T2.fd_create_time < ?
  AND T1.fd_settle_state = 1
"""

STAMP_TAX_DETAIL_REPORT = ReportDefinition(
    key="contract_stamp_tax_detail",
    name="合同－印花税明细",
    description="按日期区间生成主合同、采购合同及三类结算明细工作表。",
    source_note="数据源：mod_contract_main、mod_settle_recon、mod_settle_pacon、mod_fi_expense 等。",
    filters=_DATE_RANGE_FILTERS,
    sheets=(
        _sheet("主合同", _STAMP_MAIN_BASE, parameter_keys=("start_date", "end_date"), order_by="[合同编号]"),
        _sheet("采购合同", _STAMP_PURCHASE_BASE, parameter_keys=("start_date", "end_date"), order_by="[合同编号]"),
        _sheet("收入合同结算", _STAMP_INCOME_SETTLEMENT_BASE, parameter_keys=("start_date", "end_date")),
        _sheet("支出合同结算", _STAMP_EXPENSE_SETTLEMENT_BASE, parameter_keys=("start_date", "end_date")),
        _sheet("报销结算", _STAMP_REIMBURSEMENT_BASE, parameter_keys=("start_date", "end_date")),
    ),
)


REPORTS: dict[str, ReportDefinition] = {
    report.key: report
    for report in (
        EMPLOYEE_REPORT,
        CLAIM_DETAIL_REPORT,
        CLAIM_AMOUNT_REPORT,
        EXPENSE_INVOICE_REPORT,
        CONTRACT_AMOUNT_SUMMARY_REPORT,
        CONTRACT_AMOUNT_DETAIL_REPORT,
        STAMP_TAX_DETAIL_REPORT,
    )
}


# 第二道代码防线：本应用的远程查询仅能是单条 SELECT。
# 最终写保护仍必须由 SQL Server 中的专用只读账号和对象授权实现。
_BLOCKED_SQL_TOKENS = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|TRUNCATE|ALTER|DROP|CREATE|EXEC|EXECUTE|"
    r"GRANT|REVOKE|DENY|BACKUP|RESTORE|DBCC|INTO|OPENROWSET|OPENDATASOURCE)\b",
    re.IGNORECASE,
)


def validate_read_only_sql(sql: str) -> None:
    """拒绝非 SELECT、注释、多语句及写入/管理关键词。"""
    normalized = " ".join(sql.split())
    if not normalized.upper().startswith("SELECT "):
        raise ValueError("只允许执行 SELECT 查询。")
    if ";" in normalized or "--" in normalized or "/*" in normalized:
        raise ValueError("查询模板不允许包含多语句或 SQL 注释。")
    if _BLOCKED_SQL_TOKENS.search(normalized):
        raise ValueError("查询模板包含不允许的写入或管理操作。")


def validate_report_read_only(report: ReportDefinition) -> None:
    """确保该报表每个工作表的计数、预览和导出 SQL 都符合只读限制。"""
    if not report.sheets:
        raise ValueError("报表至少需要一个查询工作表。")
    for sheet in report.sheets:
        validate_sheet_read_only(sheet)


def validate_sheet_read_only(sheet: ReportSheet) -> None:
    """确保单个工作表对应的所有查询均为只读。"""
    for sql in (sheet.data_sql, sheet.preview_sql, sheet.count_sql):
        validate_read_only_sql(sql)


def get_report(report_key: str) -> ReportDefinition:
    """返回批准报表；未知报表不得执行。"""
    try:
        report = REPORTS[report_key]
        validate_report_read_only(report)
        return report
    except KeyError as exc:
        raise ValueError("未授权的报表类型。") from exc


def available_reports(mode: str) -> tuple[ReportDefinition, ...]:
    """演示模式仅展示本地可运行的员工测试报表。"""
    reports = tuple(REPORTS.values())
    return tuple(report for report in reports if mode != "demo" or report.supports_demo)


def build_params(sheet: ReportSheet, filters: Mapping[str, Any]) -> list[Any]:
    """按固定占位符顺序绑定页面参数，绝不拼接用户输入。"""
    try:
        return [filters[key] for key in sheet.parameter_keys]
    except KeyError as exc:
        raise ValueError("报表筛选参数不完整。") from exc
