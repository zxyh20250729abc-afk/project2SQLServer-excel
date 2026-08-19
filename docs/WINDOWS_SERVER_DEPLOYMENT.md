# Windows 服务器部署操作手册（V3）

## 1. 用途和安全要求

本手册用于将 `project2SQLServer导入excel系统` 部署到 Windows 服务器。应用使用 SQL Server 专用只读账号访问 `ekp_dyy_test`，内网用户只访问 Streamlit 网页。

必须遵守：

1. 应用账号只能对已批准的业务表/视图执行 `SELECT`。
2. 禁止授予 `INSERT`、`UPDATE`、`DELETE`、`EXECUTE`、`ALTER`、`CREATE`、`CONTROL`、`db_owner`、`db_datawriter` 或 `sysadmin`。
3. 部署包不包含 `.streamlit\secrets.toml`、真实密码、`.venv`、`.git`、日志、审计库和导出 Excel。
4. 服务器更新时必须保留服务器自己的 `secrets.toml`。
5. 终端用户只访问 TCP `8501`，不向终用户开放 SQL Server `1433`。

---

## 2. Windows 首次部署

### 2.1 检查前置环境

需要 Python 3.12 或更高版本，以及 Microsoft ODBC Driver 17 或 18 for SQL Server。

```powershell
py --version
python -c "import pyodbc; print(pyodbc.drivers())"
```

`secrets.toml` 中的 `driver` 必须与第二条命令的输出完全一致。

### 2.2 解压并进入项目根目录

```powershell
Set-Location "D:\SQLExcelExport\project2SQLServer导入excel系统"
Get-Location
Test-Path .\app.py
Test-Path .\requirements.txt
```

两个 `Test-Path` 都必须返回 `True`。

### 2.3 创建独立虚拟环境

```powershell
py -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

激活成功后左侧应显示 `(.venv)`。CMD 的激活命令是：

```bat
.venv\Scripts\activate.bat
```

---

## 3. 单独分点一：创建专用只读账号

> 由 DBA 在 SSMS 中执行。将示例密码替换为符合公司策略的强密码，不得将真实密码写入 Git、文档或 ZIP。

### 3.1 创建服务器级 LOGIN

```sql
USE [master];
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.server_principals
    WHERE name = N'report_export_reader'
)
BEGIN
    CREATE LOGIN [report_export_reader]
    WITH PASSWORD = N'请替换为真实强密码',
         CHECK_POLICY = ON,
         CHECK_EXPIRATION = ON,
         DEFAULT_DATABASE = [ekp_dyy_test];
END;
GO
```

### 3.2 在目标库创建 USER

```sql
USE [ekp_dyy_test];
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.database_principals
    WHERE name = N'report_export_reader'
)
BEGIN
    CREATE USER [report_export_reader]
    FOR LOGIN [report_export_reader];
END;
GO

GRANT CONNECT TO [report_export_reader];
GO
```

### 3.3 确认账号不具有高权限

用 `report_export_reader` 登录 SSMS 后执行：

```sql
SELECT
    SYSTEM_USER AS 登录名,
    USER_NAME() AS 数据库用户,
    DB_NAME() AS 当前数据库,
    IS_SRVROLEMEMBER(N'sysadmin') AS 是否sysadmin,
    IS_MEMBER(N'db_owner') AS 是否db_owner,
    IS_MEMBER(N'db_datawriter') AS 是否db_datawriter;
```

正确结果：当前库为 `ekp_dyy_test`，三个高权限标志均为 `0`。

---

## 4. 单独分点二：对所查询的 14 个业务对象逐个授予 SELECT

> 以下是当前 6 项正式业务查询使用的全部对象。由 DBA 在 `ekp_dyy_test` 执行。

```sql
USE [ekp_dyy_test];
GO

GRANT SELECT ON OBJECT::dbo.sys_org_element       TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.mod_contract_main     TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.mod_contract_close    TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.mod_fi_claim          TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.mod_fi_expense        TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.mod_fi_invoice_detail TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.mod_base_source_fund  TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.mod_base_con_type      TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.mod_base_grade_cate    TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.mod_base_price_fix     TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.mod_base_con_cglx      TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.mod_settle_recon       TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.mod_settle_pacon       TO [report_export_reader];
GRANT SELECT ON OBJECT::dbo.lbpm_audit_note        TO [report_export_reader];
GO
```

### 4.1 用应用账号批量核对对象和权限

```sql
USE [ekp_dyy_test];
GO

SELECT
    V.object_name AS 对象名,
    OBJECT_ID(N'dbo.' + V.object_name) AS 对象ID,
    HAS_PERMS_BY_NAME(N'dbo.' + V.object_name, 'OBJECT', 'SELECT') AS 是否可SELECT
FROM (VALUES
    (N'sys_org_element'),
    (N'mod_contract_main'),
    (N'mod_contract_close'),
    (N'mod_fi_claim'),
    (N'mod_fi_expense'),
    (N'mod_fi_invoice_detail'),
    (N'mod_base_source_fund'),
    (N'mod_base_con_type'),
    (N'mod_base_grade_cate'),
    (N'mod_base_price_fix'),
    (N'mod_base_con_cglx'),
    (N'mod_settle_recon'),
    (N'mod_settle_pacon'),
    (N'lbpm_audit_note')
) AS V(object_name)
ORDER BY V.object_name;
```

已批准对象的 `对象ID` 必须不为 `NULL`，`是否可SELECT` 必须为 `1`。新增表/视图后，DBA 必须单独增加对应 `GRANT SELECT`。

### 4.2 生产库不推荐的全库授权

```sql
ALTER ROLE [db_datareader] ADD MEMBER [report_export_reader];
```

该方式会允许读取整库普通用户表/视图。正式环境应使用上述逐对象 `GRANT SELECT`，或只授权 DBA 建立的经审批报表视图。

---

## 5. 创建数据库配置文件

### 5.1 复制样例并填写

```powershell
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
notepad .streamlit\secrets.toml
```

若真实配置已存在，先备份：

```powershell
Copy-Item .streamlit\secrets.toml .streamlit\secrets.toml.bak
```

标准格式：

```toml
[sqlserver]
server = "127.0.0.1,1433"
database = "ekp_dyy_test"
username = "report_export_reader"
password = "仅在服务器填写真实密码"
driver = "ODBC Driver 17 for SQL Server"
encrypt = false
trust_server_certificate = true
connection_timeout_seconds = 15
query_timeout_seconds = 60
allowed_logins = ["report_export_reader"]

[app]
mode = "sqlserver"
max_export_rows = 1048576
audit_db_path = "audit.db"
```

安全检查必填字段（不输出密码）：

```powershell
python -c "import tomllib; d=tomllib.load(open(r'.streamlit\secrets.toml','rb')); s=d.get('sqlserver',{}); r=('server','database','username','password','driver'); print('缺少字段：',[k for k in r if not s.get(k)])"
```

正确输出是 `缺少字段： []`。

---

## 6. 单独分点三：将 secrets.toml 转换为 UTF-8

### 6.1 ANSI/GBK 转 UTF-8 无 BOM

```powershell
$p = ".streamlit\secrets.toml"
$text = Get-Content -Raw -Encoding Default $p
[System.IO.File]::WriteAllText(
    (Resolve-Path $p),
    $text,
    (New-Object System.Text.UTF8Encoding($false))
)
```

### 6.2 已是 UTF-8，只统一为 UTF-8 无 BOM

```powershell
$p = ".streamlit\secrets.toml"
$text = [System.IO.File]::ReadAllText(
    (Resolve-Path $p),
    [System.Text.Encoding]::UTF8
)
[System.IO.File]::WriteAllText(
    (Resolve-Path $p),
    $text,
    (New-Object System.Text.UTF8Encoding($false))
)
```

### 6.3 转换后验证 TOML 和 UTF-8

```powershell
python -c "import tomllib; tomllib.load(open(r'.streamlit\secrets.toml','rb')); print('TOML格式及UTF-8编码正确')"
```

必须看到 `TOML格式及UTF-8编码正确`。若文件是 UTF-16，建议从 `secrets.toml.example` 重新复制后填写，不要反复猜测原编码。

---

## 7. 验证连接和报表权限

```powershell
python scripts\verify_sqlserver_connection.py --report contract_amount_summary
python scripts\verify_sqlserver_connection.py --report contract_stamp_tax_detail
```

验证结果中“可读取”表示 SQL 和权限正常。匹配 `0` 行不是错误，只表示脚本默认的当前月内没有符合条件的数据。

印花税的三类结算使用 `lbpm_audit_note.fd_create_time` 的“结束节点”时间；主合同使用备案时间；采购合同使用签订时间。

用 SSMS `>= '2025-05-01' AND < '2025-07-01'` 和网站比较时，网站应设置：

- 开始日期：`2025年5月1日`；
- 结束日期：`2025年6月30日`；
- 点击“全选”；
- 不增加其他筛选条件。

---

## 8. 启动和内网访问

```powershell
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

本机访问 `http://127.0.0.1:8501`，内网访问 `http://服务器IP:8501`。

```powershell
Test-NetConnection 127.0.0.1 -Port 8501
netstat -ano | findstr :8501
```

Windows 防火墙只向获批内网网段开放 TCP 8501。

---

## 9. 升级到新部署包

1. 在旧目录备份配置：

   ```powershell
   Copy-Item .streamlit\secrets.toml ..\secrets.toml.server.bak
   ```

2. 在运行 Streamlit 的 PowerShell 按 `Ctrl+C`。
3. 把新 ZIP 解压到新目录，不要在压缩包内运行。
4. 把备份配置复制到新目录：

   ```powershell
   Copy-Item ..\secrets.toml.server.bak .streamlit\secrets.toml
   ```

5. 在新目录重新创建 `.venv`，不复制旧/Mac 虚拟环境。
6. 重做 UTF-8、连接、权限和报表验证。
7. 启动新版，浏览器按 `Ctrl+F5`。

```powershell
Get-Location
python -c "import streamlit; print(streamlit.__version__); print(streamlit.__file__)"
```

---

## 10. 近两日部署问题汇总表

| 问题/现象 | 问题所在 | 原因 | 解决办法 | 可复制粘贴的命令/代码 |
| --- | --- | --- | --- | --- |
| `requirements.txt` 不存在 | PowerShell 目录 | 未进入项目根目录 | 进入同时存在 `app.py` 和 `requirements.txt` 的目录 | `Get-Location`<br>`Test-Path .\app.py`<br>`Test-Path .\requirements.txt` |
| `Copy-Item` 不是命令 | CMD/PowerShell | 在 CMD 中使用了 PowerShell 命令 | 改用 PowerShell，或 CMD 使用 `copy` | PowerShell：`Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml`<br>CMD：`copy .streamlit\secrets.toml.example .streamlit\secrets.toml` |
| PowerShell 出现 `>>` | PowerShell 输入 | 引号/括号未闭合 | 取消当前输入后重新整行粘贴 | `Ctrl+C` |
| `ModuleNotFoundError: pandas` | Python 环境 | 虚拟环境未激活或未安装依赖 | 激活当前 `.venv` 后安装 | `.\.venv\Scripts\Activate.ps1`<br>`python -m pip install -r requirements.txt` |
| 数据库配置缺少字段 | `secrets.toml` | 缺少 `server/database/username/password/driver` 或分组不对 | 从样例重建并检查必填键 | `python -c "import tomllib; d=tomllib.load(open(r'.streamlit\secrets.toml','rb')); s=d.get('sqlserver',{}); r=('server','database','username','password','driver'); print([k for k in r if not s.get(k)])"` |
| `secrets.toml.txt` | Windows 扩展名 | 记事本自动加 `.txt` | 显示扩展名后改名 | `Get-ChildItem .streamlit -Force`<br>`Rename-Item .streamlit\secrets.toml.txt secrets.toml` |
| `TOMLDecodeError` | TOML 格式 | 中文引号、多项粘成一行、开头有非法字符 | 从样例重建，用英文半角引号 | `Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml -Force` |
| `UnicodeDecodeError: utf-8` | 配置编码 | 文件是 ANSI/GBK/UTF-16 | 转为 UTF-8 无 BOM 并验证 | `$p='.streamlit\secrets.toml'; $t=Get-Content -Raw -Encoding Default $p; [IO.File]::WriteAllText((Resolve-Path $p),$t,(New-Object Text.UTF8Encoding($false)))`<br>`python -c "import tomllib; tomllib.load(open(r'.streamlit\secrets.toml','rb')); print('OK')"` |
| `IM002`/找不到数据源 | ODBC | Driver 17/18 配置与安装版本不同 | 精确填写驱动列表的名称 | `python -c "import pyodbc; print(pyodbc.drivers())"` |
| `HYT00 Login timeout expired` | 网络/TCP | IP、端口、TCP/IP 或防火墙问题 | 先测试 1433 端口 | `Test-NetConnection 192.0.2.19 -Port 1433` |
| `HY000 Protocol error in TDS stream` | ODBC/TDS | 端口、驱动、加密或证书配置不匹配 | 核对实例端口、Driver、`encrypt` 和证书 | `python -c "import pyodbc; print(pyodbc.drivers())"`<br>`Test-NetConnection 192.0.2.19 -Port 1433` |
| `18456` 登录失败 | SQL Server 认证 | 账号/密码、混合认证、默认库或登录状态问题 | 用相同 SQL 账号在 SSMS 登录并查 State | `SELECT SYSTEM_USER, ORIGINAL_LOGIN(), DB_NAME();` |
| 应用拒绝当前账号 | 只读安全检查 | `allowed_logins` 不匹配或账号是高权限 | 使用真实只读登录名并移除高权限 | `SELECT SYSTEM_USER, ORIGINAL_LOGIN(), IS_SRVROLEMEMBER(N'sysadmin'), IS_MEMBER(N'db_owner'), IS_MEMBER(N'db_datawriter');` |
| `208` 对象名无效 | 报表/权限 | 连接错库、架构不同，或新表对应用账号不可见 | 用应用账号检查 DB、对象ID 和 SELECT | `SELECT DB_NAME(), OBJECT_ID(N'dbo.mod_base_price_fix'), HAS_PERMS_BY_NAME(N'dbo.mod_base_price_fix','OBJECT','SELECT');` |
| `229` 拒绝 SELECT | 对象授权 | 新表/视图没有单独授权 | DBA 补充最小权限 | `USE [ekp_dyy_test]; GRANT SELECT ON OBJECT::dbo.mod_base_price_fix TO [report_export_reader];` |
| DBA 能查表，应用仍报错 | SSMS/应用账号不同 | DBA 看到对象不等于只读账号有权限 | 用 `report_export_reader` 登录 SSMS 重做检查 | `SELECT SYSTEM_USER, USER_NAME(), DB_NAME();` |
| `mod_base_price_fix` 存在但印花税失败 | 新表权限 | 表加入查询后未向只读账号授权 | 单独授予 SELECT | `GRANT SELECT ON OBJECT::dbo.mod_base_price_fix TO [report_export_reader];` |
| 印花税三类结算匹配 `0` 行 | 日期/测试数据 | 验证脚本默认当前月，结束节点数据最晚只到 2025-11 | 不是错误；网站选有数据的历史日期 | `SELECT MIN(fd_create_time), MAX(fd_create_time), COUNT_BIG(*) FROM dbo.lbpm_audit_note WHERE fd_fact_node_name=N'结束节点';` |
| 网站与 SSMS 日期看似不一致 | 日期边界 | SSMS 用 `<次月1日`，网站结束日期包含当天 | SSMS `<2025-07-01` 对应网站 `2025-06-30` | 网站：开始 `2025-05-01`，结束 `2025-06-30` |
| 首次进入页面未立即读库 | 网页触发 | 首次只显示默认条件，条件变化后查询 | 设置日期或改变查看字段 | 例：开始 `2025-05-01`，结束 `2025-06-30` |
| 印花税字段不显示 | 旧包/字段别名 | 服务器仍运行旧版本 | 更新完整包、保留 `secrets.toml`、重启 | `Get-Location`<br>`python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501` |
| 夜间模式输入框仍浅色 | 旧 `app.py`/缓存 | 服务器旧包或浏览器保留旧 CSS | 更新包、重启、强刷 | `Ctrl+C`<br>`python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501`<br>浏览器：`Ctrl+F5` |
| Excel 已生成，下载报 `Failed to fetch dynamically imported module` | Streamlit 静态 JS | 更新后旧页面引用了旧 `DownloadButton.*.js` | 重启 Streamlit，清理浏览器缓存或用无痕窗口 | `Ctrl+C`<br>`python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501`<br>浏览器：`Ctrl+F5` |
| `DownloadButton.*.js` 返回 `404` | 静态文件 | 旧 hash 被缓存或多个 Streamlit 进程版本不一致 | 确认只有一个 8501 进程，重启后强刷 | `netstat -ano | findstr :8501`<br>`python -m streamlit --version` |
| 服务器本机可打开，其他电脑不可访问 | 绑定/防火墙 | 只绑定本机或 8501 未开放 | 绑定 `0.0.0.0`，开放获批内网规则 | `python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501`<br>`Test-NetConnection 服务器IP -Port 8501` |
| 关闭 PowerShell 后网页停止 | 运行方式 | Streamlit 是前台进程 | 测试保持窗口；上线由管理员配置 Windows 服务/守护 | `netstat -ano | findstr :8501` |
| PowerShell 深蓝背景上错误不清晰 | PowerShell 显示 | 默认颜色对比度不足 | 当前窗口改黑底浅色字 | `$Host.UI.RawUI.BackgroundColor='Black'; $Host.UI.RawUI.ForegroundColor='Gray'; $Host.PrivateData.ErrorForegroundColor='White'; Clear-Host` |
| 升级后仍是旧问题 | 目录/进程 | 仍从旧日期目录启动，或旧 PID 未停 | 检查目录、PID 和 Streamlit 路径 | `Get-Location`<br>`netstat -ano | findstr :8501`<br>`python -c "import streamlit; print(streamlit.__file__)"` |
| `KeyError: 'age'` | 旧版验证脚本 | 部署目录中混入旧脚本 | 使用最新完整部署包 | `Get-Location`<br>`python scripts\verify_sqlserver_connection.py --report contract_amount_summary` |

---

## 11. 上线验收清单

1. 服务器运行的是最新解压目录。
2. `.venv` 在当前 Windows 服务器重新创建。
3. `secrets.toml` 通过 TOML 和 UTF-8 验证。
4. `database = "ekp_dyy_test"`，Driver 与实际安装一致。
5. `allowed_logins` 与 `SYSTEM_USER` 一致。
6. 只读账号不是 `sysadmin`、`db_owner` 或 `db_datawriter`。
7. 14 个正式业务对象逐项核对，已批准对象 `SELECT = 1`。
8. `contract_amount_summary` 和 `contract_stamp_tax_detail` 验证通过。
9. 用有数据的历史日期核对印花税五个页签。
10. 夜间模式、输入框、分页、Excel 生成和下载均通过。
11. 浏览器 `Ctrl+F5` 后无旧静态 JS 错误。
12. ZIP 不包含密码、`secrets.toml`、`.venv`、`.git`、日志、审计库或导出 Excel。
