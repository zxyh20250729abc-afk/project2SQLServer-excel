"""面向业务人员的数据目录。

这里把底层 SQL 报表转换为业务主题、查询事项和中文字段说明。普通用户只会接触
本模块中的业务语言；表名、字段名及关联 SQL 仍由 reports.py 受控维护。
"""

from __future__ import annotations

from dataclasses import dataclass

from reports import REPORTS, ReportDefinition


@dataclass(frozen=True)
class BusinessField:
    """一个可展示或导出的已批准业务字段。"""

    column_name: str
    label: str
    description: str
    recommended: bool = False


@dataclass(frozen=True)
class DatasetPresentation:
    """一个用户可理解的查询事项，与一个受控报表定义一一对应。"""

    report_key: str
    domain_key: str
    domain_name: str
    title: str
    description: str
    keywords: tuple[str, ...]
    fields: tuple[BusinessField, ...]
    is_system_test: bool = False

    @property
    def report(self) -> ReportDefinition:
        return REPORTS[self.report_key]


def _fields(*items: tuple[str, str, str, bool]) -> tuple[BusinessField, ...]:
    return tuple(BusinessField(*item) for item in items)


DATASETS: tuple[DatasetPresentation, ...] = (
    DatasetPresentation(
        report_key="finance_expense_invoice",
        domain_key="finance",
        domain_name="财务数据",
        title="查询报销发票",
        description="查看已入账报销单对应的发票、金额、税额和开票信息。",
        keywords=("报销", "发票", "税额", "入账", "凭证"),
        fields=_fields(
            ("部门", "部门", "报销所属部门", True),
            ("报销单号", "报销单号", "报销业务单据编号", True),
            ("发票号码", "发票号码", "发票上的号码", True),
            ("开票日期", "开票日期", "发票开具日期", True),
            ("价税合计", "价税合计", "发票含税总金额", True),
            ("税额", "税额", "发票税额", True),
            ("用友凭证号", "用友凭证号", "已入账的财务凭证号", False),
            ("用友记账年份", "入账年份", "财务系统记账年份", False),
            ("用友记账月份", "入账月份", "财务系统记账月份", False),
            ("发票类型", "发票类型", "增值税发票等业务类型", False),
            ("发票代码", "发票代码", "发票代码", False),
            ("税率", "税率", "发票适用税率", False),
            ("不含税金额", "不含税金额", "未含税金额", False),
            ("验真状态", "验真状态", "发票验真结果", False),
            ("销售方", "销售方", "发票销售方名称", False),
        ),
    ),
    DatasetPresentation(
        report_key="finance_claim_detail",
        domain_key="finance",
        domain_name="财务数据",
        title="查询认款明细",
        description="查看认款单、项目、合同、认款金额和管理费明细。",
        keywords=("认款", "管理费", "付款方", "项目", "合同"),
        fields=_fields(
            ("申请部门", "申请部门", "认款业务所属部门", True),
            ("申请时间", "申请时间", "认款单创建时间", True),
            ("认款单编号", "认款单编号", "认款业务单据编号", True),
            ("项目名称", "项目名称", "对应项目名称", True),
            ("合同编号", "合同编号", "关联合同编号", True),
            ("认款金额", "认款金额", "本次认款金额", True),
            ("管理费", "管理费", "对应管理费金额", True),
            ("付款方", "付款方", "实际付款单位或个人", True),
            ("申请人", "申请人", "认款单申请人", False),
            ("认款单位", "认款单位", "认款归属单位", False),
            ("业主单位", "业主单位", "合同业主单位", False),
            ("合同金额", "合同金额", "关联合同金额", False),
            ("资金来源", "资金来源", "认款资金来源", False),
            ("业务类型", "业务类型", "认款业务分类", False),
            ("用友记账年月", "入账年月", "财务系统记账年月", False),
        ),
    ),
    DatasetPresentation(
        report_key="finance_claim_amount",
        domain_key="finance",
        domain_name="财务数据",
        title="查询认款汇总",
        description="按部门和入账月份汇总认款金额及管理费。",
        keywords=("认款", "汇总", "管理费", "部门"),
        fields=_fields(
            ("申请部门", "申请部门", "认款业务所属部门", True),
            ("用友记账年月", "入账年月", "财务系统记账年月", True),
            ("认款金额", "认款金额", "部门当期认款金额合计", True),
            ("管理费", "管理费", "部门当期管理费合计", True),
        ),
    ),
    DatasetPresentation(
        report_key="contract_amount_summary",
        domain_key="contract",
        domain_name="合同管理",
        title="查询合同金额汇总",
        description="按部门和备案月份统计合同金额，已统筹补充协议和终止合同。",
        keywords=("合同", "金额", "汇总", "补充协议", "终止合同"),
        fields=_fields(
            ("部门", "部门", "合同归属部门", True),
            ("合同备案时间", "合同备案时间", "合同在系统完成备案的月份", True),
            ("合同金额", "合同金额", "已统筹补充协议和终止合同后的金额", True),
        ),
    ),
    DatasetPresentation(
        report_key="contract_amount_detail",
        domain_key="contract",
        domain_name="合同管理",
        title="查询合同金额明细",
        description="分别查看主合同、补充协议及终止合同明细。",
        keywords=("合同", "明细", "补充协议", "终止"),
        fields=_fields(
            ("部门名称", "部门", "合同归属部门", True),
            ("合同编号", "合同编号", "合同备案编号", True),
            ("合同金额", "合同金额", "主合同或补充协议金额", True),
            ("合同备案时间", "合同备案时间", "合同备案月份", True),
            ("合同类型", "合同类型", "主合同、补充协议等分类", True),
            ("终止合同金额", "终止合同金额", "终止合同对应金额", True),
            ("终止协议签订时间", "终止协议时间", "终止协议签订月份", False),
        ),
    ),
    DatasetPresentation(
        report_key="contract_stamp_tax_detail",
        domain_key="contract",
        domain_name="合同管理",
        title="查询印花税明细",
        description="查看主合同、采购合同和各类结算的印花税相关明细。",
        keywords=("印花税", "合同", "采购", "结算"),
        fields=_fields(
            ("签订单位", "签订单位", "合同签订单位", True),
            ("部门名称", "部门", "合同归属部门", True),
            ("申请部门", "申请部门", "结算申请所属部门", True),
            ("合同编号", "合同编号", "合同备案编号", True),
            ("合同名称", "合同名称", "合同主题或名称", True),
            ("合同金额", "合同金额", "合同金额", True),
            ("结算金额", "结算金额", "本次结算金额", True),
            ("合同备案时间", "合同备案时间", "合同备案日期", False),
            ("合同签订时间", "合同签订时间", "采购合同签订日期", False),
            ("合同类别", "合同类别", "合同业务类别", False),
            ("合同定价类型", "合同定价类型", "合同定价方式", False),
            ("结算日期", "结算日期", "结算完成日期", False),
            ("是否约定金额", "是否约定金额", "合同是否约定金额", False),
        ),
    ),
    DatasetPresentation(
        report_key="employee_list",
        domain_key="system",
        domain_name="系统验证",
        title="验证员工测试数据",
        description="用于验证只读连接、筛选和 Excel 导出流程，不属于正式业务查询。",
        keywords=("测试", "员工", "连接验证"),
        fields=_fields(
            ("人员编号", "人员编号", "测试员工编号", True),
            ("姓", "姓", "测试员工姓氏", True),
            ("名", "名", "测试员工名字", True),
            ("年龄", "年龄", "测试员工年龄", True),
            ("部门", "部门", "测试员工部门", True),
            ("薪资", "薪资", "测试员工薪资", False),
        ),
        is_system_test=True,
    ),
)


def available_datasets(mode: str) -> tuple[DatasetPresentation, ...]:
    """返回当前运行模式可用的业务查询事项。"""
    if mode == "demo":
        return tuple(dataset for dataset in DATASETS if dataset.report.supports_demo)
    return DATASETS


def get_dataset(report_key: str) -> DatasetPresentation:
    for dataset in DATASETS:
        if dataset.report_key == report_key:
            return dataset
    raise ValueError("未找到已批准的业务查询事项。")


def search_datasets(datasets: tuple[DatasetPresentation, ...], query: str) -> tuple[DatasetPresentation, ...]:
    """按用户输入的业务词过滤查询事项，不涉及 SQL 或数据库检索。"""
    normalized = query.strip().casefold()
    if not normalized:
        return datasets
    return tuple(
        dataset
        for dataset in datasets
        if normalized in " ".join((dataset.domain_name, dataset.title, dataset.description, *dataset.keywords)).casefold()
    )
