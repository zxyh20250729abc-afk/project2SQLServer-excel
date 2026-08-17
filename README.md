# project2SQLServer导入excel系统

面向行政、财务、合同等非技术人员的 SQL Server → Excel 数据查询助手。用户使用业务语言选择查询事项、填写条件、选择需要的信息并导出 Excel；系统在后台运行经审批的参数化只读查询。

## 当前功能

- 首页按“财务数据 / 合同管理”两大板块进入，再选择具体查询事项；不显示数据库表名、字段名或 SQL
- 已内置 6 项真实业务查询：认款明细、认款汇总、报销发票、合同金额汇总、合同金额明细、印花税明细
- 用户先选择要查看和导出的中文字段，再按业务语言填写年度、月份、日期等基础范围，并仅从已选字段中叠加“包含、等于、数值上下限、时间区间”筛选
- 后台受控执行已批准的多表关联查询；用户不需要理解 `INNER JOIN`、表结构或关联规则
- 首版不要求登录、姓名或工号；用户打开页面即可开始查询
- 多结果集查询导出为一个 Excel 的多个工作表（合同金额明细、印花税明细）
- 员工测试数据仅用于模拟演示和 SQL Server 连通性验证，并收纳在“系统验证（管理员使用）”中
- SQL Server 只读意图连接与参数化 SQL
- 强制使用 TCP 连接 SQL Server，避免客户端协议自动协商
- 左侧紧凑设置字段与条件，右侧实时展示总行数和前 100 行预览；仅在确认后生成全量 Excel
- 冻结表头、筛选、自动列宽和标准文件命名
- SQLite 导出审计日志
- 凭据与代码分离，禁止硬编码

## 立即演示（无需 SQL Server）

在没有 `.streamlit/secrets.toml` 的情况下，应用会自动进入**模拟数据模式**。直接运行：

```bash
cd "/Users/remi/Documents/Codex/2026-07-22/wo/project2SQLServer导入excel系统"
source .venv/bin/activate
streamlit run app.py
```

页面会显示“模拟数据模式”提示；可按部门、年龄范围筛选模拟员工，选择展示字段、预览结果并下载 Excel。模拟数据不会访问网络或 SQL Server。

真实 SQL Server 模式会运行代码中版本管理的已批准业务查询。除年度、月份、日期等基础条件外，用户还可按页面展示的已批准业务字段叠加筛选。每条新增条件只会作用于固定查询的结果列，并以参数化 `WHERE` 条件执行；不会根据数据库任意字段自动开放敏感字段，也不会执行写入操作。多工作表报表中，某项条件只会作用于包含该业务字段的工作表，页面会明确提示。

如已创建密钥文件，请在 `[app]` 中写入 `mode = "demo"` 也可强制使用模拟数据。接入真实数据库时再改为 `mode = "sqlserver"`。

## 首次配置

所有命令必须在**项目根目录**（可看到 `requirements.txt` 的目录）执行。先进入目录：

```bash
cd "/Users/remi/Documents/Codex/2026-07-22/wo/project2SQLServer导入excel系统"
```

1. 创建虚拟环境并安装依赖：

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. 创建密钥文件。不要提交它：

   ```bash
   mkdir -p .streamlit
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```

3. 在 `.streamlit/secrets.toml` 填写数据库的只读账户。上线前必须确认：

   - 已安装目标平台适用的 SQL Server ODBC Driver；
   - macOS 本地开发除 `unixODBC` 外，还需要安装 Microsoft ODBC Driver 18 for SQL Server；当前环境尚未检测到该 Microsoft 驱动；
   - 数据库账户仅具有当前启用的测试表或业务报表批准视图/表的 `SELECT` 权限；
   - `encrypt` 与证书策略符合公司的数据库安全要求。

4. 当前项目已内置 6 项业务查询。生产上线前，请 DBA 与业务负责人核对 `reports.py` 中每项查询的来源对象、关联口径、字段口径和 `SELECT` 权限；不要把用户输入拼接到 SQL。

5. 如需新增业务事项、字段或多表关联，由产品/业务人员说明业务口径，开发人员在 `catalog.py` 增加用户可理解的名称与字段说明，并在 `reports.py` 增加对应的固定只读查询；经 DBA 审批、测试和代码审查后才可上线。不要开放“任意选表、任意关联、任意 SQL”。

6. 启动：

   ```bash
   streamlit run app.py
   ```

## 测试

```bash
pytest
python -m py_compile app.py audit.py catalog.py database.py exporter.py reports.py
```

## 安全交付与真实数据库接入

```bash
python scripts/package_release.py
```

此命令会在上级 `outputs/` 目录创建不含密钥、审计日志、导出文件和虚拟环境的交付 ZIP。真实 SQL Server 接入和只读权限核验见 [docs/REAL_SQLSERVER_VALIDATION.md](docs/REAL_SQLSERVER_VALIDATION.md)，完整审查结论见 [SECURITY_REVIEW.md](SECURITY_REVIEW.md)。

推荐的推广部署方式是将应用部署在 SQL Server 所在的 Windows 服务器，应用通过本机 `127.0.0.1` 读取数据库，终端用户只访问网页。详见 [docs/WINDOWS_SERVER_DEPLOYMENT.md](docs/WINDOWS_SERVER_DEPLOYMENT.md)。可使用 `python scripts/verify_sqlserver_connection.py --report contract_stamp_tax_detail` 在上线前核验指定业务报表的只读访问权限。

## 交付前检查

- 不提交 `.streamlit/secrets.toml`、`audit.db`、导出文件或 `.venv`。
- 实际数据库凭据、对象授权、跨表关联口径和可展示字段已由 DBA/业务负责人审核。
- 正常、无数据、筛选条件非法、连接失败和大结果集等场景均已测试。
- 每次生成全量 Excel 均写入审计日志；首版不收集姓名或工号，日志以“匿名访问”记录，且不含数据库密码或结果明细。实时预览不写审计，避免因用户逐字调整条件而产生大量无意义日志。
