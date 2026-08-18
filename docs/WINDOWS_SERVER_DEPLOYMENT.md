# Windows 服务器部署（V3）

目标：应用与 SQL Server 部署在同一台 Windows 服务器，应用只通过 `127.0.0.1:1433` 访问数据库；终端用户只访问“数据查询助手”网页，不接触数据库账号、表名或 SQL。

## 1. 服务器前置条件

- 已安装 Python 3.12 或更高版本，并在安装界面勾选 “Add Python to PATH”。
- 已安装 Microsoft ODBC Driver 18 for SQL Server。
- SQL Server 位于本机，已启用 TCP 端口 `1433`。
- 已创建专用只读账号 `report_export_reader`，且仅有已批准测试表或业务报表视图/表的 `SELECT` 权限。

## 2. 部署项目

将安全交付 ZIP 解压到例如 `C:\SQLExcelExport\project2SQLServer导入excel系统`。在该目录打开 PowerShell，执行：

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
notepad .streamlit\secrets.toml
```

将密钥文件中的 SQL Server 配置填写为：

```toml
[sqlserver]
server = "127.0.0.1,1433"
database = "db_test0"
username = "report_export_reader"
password = "仅在服务器填写，不发送、不提交"
driver = "ODBC Driver 18 for SQL Server"
encrypt = false
trust_server_certificate = true
allowed_logins = ["report_export_reader"]

[app]
mode = "sqlserver"
max_export_rows = 1048576
audit_db_path = "audit.db"
```

`db_test0` 和 `dbo.employees` 仅适用于连通性测试。运行真实业务查询时，应将 `database` 改为业务数据库，并由 DBA 授予每项已批准查询所需对象的 SELECT 权限。`encrypt = false` 仅适用于此 MVP 的本机测试；正式上线应部署受信任证书后设置 `encrypt = true` 与 `trust_server_certificate = false`。

## 3. 只读连通性验证

```powershell
python scripts\verify_sqlserver_connection.py --report employee_list
```

员工测试通过后，部署真实业务库前还应核验实际查询，例如：`python scripts\verify_sqlserver_connection.py --report contract_stamp_tax_detail`。所有核验只执行 `SELECT`，不会修改 SQL Server 数据。

## 4. 启动应用

```powershell
streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

在服务器本机访问 `http://127.0.0.1:8501` 验证。向内网用户开放时，只创建 TCP `8501` 的 Windows 防火墙入站规则，并将远程地址范围限制为公司内网或已批准网段。

## 5. 上线边界

- 不向用户分发 `.streamlit\secrets.toml`；其中含数据库密码。
- 不向用户开放 SQL Server 的 `1433`；只有应用服务器本机使用该端口。
- 用户只访问网页 `http://服务器地址:8501`。
- 用户通过业务事项、中文条件和中文字段完成查询；多表关联由后台固定查询处理，不向用户开放任意选表、任意关联或 SQL 输入。
- 首版不要求用户登录或填写姓名工号；查询审计统一标记为“匿名访问”。如后续需要个人级审计，应接入公司统一身份认证。
- V3 运行窗口关闭后应用会停止；正式推广时应配置 Windows 服务或受控的进程守护。
