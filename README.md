# project2SQLServer导入excel系统

基于 Streamlit 的 SQL Server → Excel 工具。用户仅能选择预设业务报表和预定义条件，系统通过参数化查询读取 SQL Server，并输出格式化 `.xlsx` 文件。

## 当前功能

- 已内置 6 份真实业务统计报表：认款明细、认款金额、报销发票、合同金额汇总、合同金额明细、印花税明细
- 页面按报表显示年度、月份或日期区间等已批准条件；不开放任意 SQL 输入
- 多结果集报表导出为一个 Excel 的多个工作表（合同金额明细、印花税明细）
- 员工测试报表保留用于模拟演示和 SQL Server 连通性验证
- SQL Server 只读意图连接与参数化 SQL
- 强制使用 TCP 连接 SQL Server，避免客户端协议自动协商
- 结果总行数、前 100 行预览、Excel 下载
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

页面会显示“模拟数据模式”提示；可按部门、年龄范围筛选模拟员工，预览结果并下载 Excel。模拟数据不会访问网络或 SQL Server。

真实 SQL Server 模式会运行代码中版本管理的预设业务报表。员工测试报表会额外读取 `dbo.employees` 的字段元数据及最多 200 个部门候选值；其他业务报表只展示其固定的年度、月份、日期条件。它不会根据数据库任意字段开放敏感字段，也不会执行写入操作。

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

4. 当前项目已内置 6 份业务统计 SQL。生产上线前，请 DBA 核对 `reports.py` 中每一份报表的来源对象、字段口径和 `SELECT` 权限；不要把用户输入拼接到 SQL。

5. 启动：

   ```bash
   streamlit run app.py
   ```

## 测试

```bash
pytest
python -m py_compile app.py audit.py database.py exporter.py reports.py
```

## 安全交付与真实数据库接入

```bash
python scripts/package_release.py
```

此命令会在上级 `outputs/` 目录创建不含密钥、审计日志、导出文件和虚拟环境的交付 ZIP。真实 SQL Server 接入和只读权限核验见 [docs/REAL_SQLSERVER_VALIDATION.md](docs/REAL_SQLSERVER_VALIDATION.md)，完整审查结论见 [SECURITY_REVIEW.md](SECURITY_REVIEW.md)。

推荐的推广部署方式是将应用部署在 SQL Server 所在的 Windows 服务器，应用通过本机 `127.0.0.1` 读取数据库，终端用户只访问网页。详见 [docs/WINDOWS_SERVER_DEPLOYMENT.md](docs/WINDOWS_SERVER_DEPLOYMENT.md)。可使用 `python scripts/verify_sqlserver_connection.py --report contract_stamp_tax_detail` 在上线前核验指定业务报表的只读访问权限。

## 交付前检查

- 不提交 `.streamlit/secrets.toml`、`audit.db`、导出文件或 `.venv`。
- 实际数据库凭据和对象授权已由 DBA 审核。
- 正常、无数据、年龄范围非法、连接失败和大结果集场景均已测试。
- 每次导出均写入审计日志，且日志不含密码或结果明细。
