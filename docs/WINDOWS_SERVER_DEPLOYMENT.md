# Windows 服务器部署与故障排查（V3）

目标：应用与 SQL Server 部署在同一台 Windows 服务器时，应用使用专用只读账号访问数据库；终端用户只访问“数据查询助手”网页，不接触数据库密码、表名或 SQL。

## 1. 服务器前置条件

- 已安装 Python 3.12 或更高版本，并在安装界面勾选 “Add Python to PATH”。
- 已安装 Microsoft ODBC Driver 17 或 18 for SQL Server。
- SQL Server 位于本机时，已启用 TCP/IP，并监听固定端口（通常为 `1433`）。
- 已创建专用只读账号 `report_export_reader`，且已在目标业务数据库中建立用户映射并授予必需的 `SELECT` 权限。
- 部署目录使用普通路径，例如 `D:\SQLExcelExport\project2SQLServer导入excel系统`，不要把项目长期放在压缩包、临时目录或下载目录中运行。

先在 PowerShell 中确认环境：

```powershell
py --version
python -c "import pyodbc; print(pyodbc.drivers())"
```

`driver` 必须与第二条命令输出的名称完全一致。服务器只显示 `ODBC Driver 17 for SQL Server` 时，配置文件不能填写 18。

## 2. 进入正确的项目目录

解压部署包后，必须先进入能看到 `app.py` 和 `requirements.txt` 的项目根目录：

```powershell
Set-Location "D:\SQLExcelExport\project2SQLServer导入excel系统"
Get-Location
Test-Path .\app.py
Test-Path .\requirements.txt
```

两个 `Test-Path` 都应返回 `True`。如果在 `C:\Users\Administrator` 中直接执行项目命令，就会出现找不到 `requirements.txt`、`.streamlit` 或脚本文件的问题。

## 3. 创建独立 Python 环境并安装依赖

以下是 **PowerShell** 命令：

```powershell
py -m venv .venv
Set-ExecutionPolicy -Scope Process Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

成功激活后，命令行左侧应出现 `(.venv)`。使用 `python -m pip` 可以确保库被安装到当前虚拟环境，而不是系统的另一个 Python。

如果使用的是传统 CMD，激活命令改为：

```bat
.venv\Scripts\activate.bat
```

PowerShell 的 `Copy-Item` 不能在 CMD 中使用；CMD 中复制文件要使用 `copy`。

## 4. 创建密钥配置文件

先复制项目附带的合法 TOML 样例，再修改实际值：

```powershell
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
notepad .streamlit\secrets.toml
```

如果配置文件已存在，先备份，不要盲目覆盖：

```powershell
Copy-Item .streamlit\secrets.toml .streamlit\secrets.toml.bak
```

本机 SQL Server 的示例配置：

```toml
[sqlserver]
server = "127.0.0.1,1433"
database = "ekp_dyy_test"
username = "report_export_reader"
password = "仅在服务器填写实际密码"
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

配置规则：

- `[sqlserver]` 和 `[app]` 必须各自独占一行。
- 每个 `key = value` 必须独占一行，不能把多个设置粘成一行。
- 必须使用英文半角引号 `"`，不能使用中文弯引号 `“”`。
- 布尔值只能写小写 `true` 或 `false`，不加引号。
- 注释必须以 `#` 开头，不能把 PowerShell 命令、说明文字或 SQL 粘贴进配置文件。
- 保存时选择 **UTF-8**；不要保存为 ANSI、Unicode UTF-16 或 RTF。
- 如果密码包含反斜杠等转义字符，可以使用 TOML 单引号字面量，例如 `password = 'actual-password'`；密码本身含单引号时不适用此写法。
- `allowed_logins` 填写 SQL Server 返回的精确登录名，不要填管理员或共享账号。

### 4.1 先验证 TOML，再连数据库

```powershell
python -c "import tomllib; tomllib.load(open(r'.streamlit\secrets.toml','rb')); print('TOML格式及UTF-8编码正确')"
```

只有看到 `TOML格式及UTF-8编码正确` 后，才继续数据库验证。

### 4.2 `TOMLDecodeError: Invalid statement (line 1, column 1)`

这个错误发生在连接 SQL Server **之前**，与网络、账号、密码无关。常见原因是：

1. 文件开头有 UTF-8 BOM、UTF-16 标记或其他不可见字符。
2. 第一行不是 `[sqlserver]`，或前面混入了命令和说明文字。
3. 使用了中文弯引号。
4. 记事本把多行内容粘贴成了一行。
5. 文件实际名称是 `secrets.toml.txt`。

最可靠的修复方法是：备份旧文件，重新从样例复制，只替换配置值，然后重新执行上面的 TOML 验证命令。

如果已确认文件内容本身是 UTF-8，仅需移除 BOM，可执行：

```powershell
$p = (Resolve-Path ".streamlit\secrets.toml")
$text = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8)
[System.IO.File]::WriteAllText($p, $text, (New-Object System.Text.UTF8Encoding($false)))
```

如果文件原本是 ANSI，不要盲目执行 BOM 处理命令；应在记事本中“另存为” UTF-8，或直接从样例文件重建。

## 5. 验证 SQL Server 连接与只读权限

### 5.1 先选择正确的报表

`employee_list` 仅用于包含 `dbo.employees` 表的测试数据库：

```powershell
python scripts\verify_sqlserver_connection.py --report employee_list
```

连接 `ekp_dyy_test` 等 OA 业务库时，应验证真实存在的业务报表，例如：

```powershell
python scripts\verify_sqlserver_connection.py --report contract_amount_summary
```

所有验证只执行 `SELECT`，不会修改 SQL Server 数据。

### 5.2 确认 SSMS 和应用使用的是同一个身份

“SSMS 可以连接”不代表应用的账号配置一定正确。SSMS 必须使用与 `secrets.toml` 相同的服务器、端口、SQL Server 身份验证、用户名、密码和目标数据库。

用只读账号在 SSMS 执行：

```sql
SELECT
    SYSTEM_USER AS system_user,
    ORIGINAL_LOGIN() AS original_login,
    USER_NAME() AS database_user,
    DB_NAME() AS database_name;
```

`allowed_logins` 应与 `SYSTEM_USER`/`ORIGINAL_LOGIN()` 的实际返回值一致。

## 6. 启动应用

```powershell
python -m streamlit run app.py --server.address 0.0.0.0 --server.port 8501
```

在服务器本机先访问 `http://127.0.0.1:8501`。本机验证正常后，再向内网用户开放 TCP `8501`，远程地址限制为公司内网或已批准网段。不要向终端用户开放 SQL Server `1433`。

端口检查：

```powershell
Test-NetConnection 127.0.0.1 -Port 8501
netstat -ano | findstr :8501
```

如果浏览器出现 `Failed to fetch dynamically imported module`：

1. 在浏览器按 `Ctrl+F5` 强制刷新。
2. 关闭旧的 Streamlit 进程，重新执行启动命令。
3. 确认当前虚拟环境中的版本：`python -m streamlit --version`。
4. 重新执行 `python -m pip install -r requirements.txt`，确保前后端版本一致。

## 7. 部署问题速查表

| 错误或现象 | 所在阶段 | 主要原因 | 处理方法 |
| --- | --- | --- | --- |
| `requirements.txt` 不存在 | 安装依赖 | 没有进入项目根目录 | `Get-Location` 和 `Test-Path .\requirements.txt` 确认目录 |
| `Copy-Item` 不是命令 | 复制配置 | 在 CMD 中执行了 PowerShell 命令 | 改用 PowerShell，或在 CMD 中使用 `copy` |
| PowerShell 出现 `>>` | 输入命令 | 引号、括号或 Here-String 未闭合 | 按 `Ctrl+C` 取消，再重新输入完整命令 |
| `ModuleNotFoundError: pandas` | 加载程序 | 虚拟环境未激活，或依赖装到了另一个 Python | 确认有 `(.venv)`，再执行 `python -m pip install -r requirements.txt` |
| `TOMLDecodeError: Invalid statement` | 读取配置 | TOML 内容不合法、编码错误、BOM、弯引号或多行粘成一行 | 从 `secrets.toml.example` 重建，另存为 UTF-8，执行 TOML 验证命令 |
| `UnicodeDecodeError: utf-8` | 读取配置 | 文件保存成 ANSI 或 UTF-16 | 在记事本中另存为 UTF-8，不要只修改扩展名 |
| `IM002`/找不到数据源名 | ODBC 连接 | `driver` 名与实际安装的版本不一致 | 运行 `python -c "import pyodbc; print(pyodbc.drivers())"` 并精确填写 17 或 18 |
| `HY000 Protocol error in TDS stream` | ODBC 连接 | 驱动、加密选项、服务器地址或协议不匹配 | 使用已安装驱动的精确名称；本机测试使用 `127.0.0.1,1433`，再核对 `encrypt` 和证书设置 |
| `28000` / `18456` 登录失败 | SQL Server 身份验证 | 密码错误、登录名被禁用、未开启混合验证、默认库不可用，或 SSMS 实际用的是 Windows 账号 | 用完全相同的 SQL 账号在 SSMS 登录目标库，查看 SQL Server 日志中 18456 的 State |
| 登录成功但应用拒绝查询 | 应用权限检查 | `allowed_logins` 不匹配，或账号属于 `sysadmin`/`db_owner`/`db_datawriter` | 用只读账号查询 `SYSTEM_USER` 和 `ORIGINAL_LOGIN()`，修正名单；不要使用高权限账号 |
| SQL Server 对象名无效 `208` | 执行报表 | 连接了错误的数据库，表/视图或架构名不同，或选了测试报表 | 确认 `database`、`schema.object`和实际报表；OA 库不要验证 `employee_list` |
| 拒绝对对象的 `SELECT` 权限 `229` | 执行报表 | 账号已登录，但目标库未建用户映射，或未授予相关表/视图的 SELECT | DBA 在目标库执行 `CREATE USER ... FOR LOGIN ...`，再按批准对象 `GRANT SELECT` |
| `KeyError: 'age'` | V3 连接验证脚本 | 旧版脚本未兼容“年龄区间”复合筛选 | 单独替换 `scripts\verify_sqlserver_connection.py`；修复版本为 `df0c695` |
| “无法将 `""` 识别为命令” | PowerShell 命令行 | 错误后又输入了多余引号 | 不需要处理应用，只要重新输入正确命令 |
| 本机能打开，其他电脑无法访问 | Web 访问 | Streamlit 仅绑定本机或 Windows 防火墙未开放 8501 | 使用 `--server.address 0.0.0.0`，并仅向已批准内网网段开放 8501 |
| 关闭 PowerShell 后页面停止 | 运行阶段 | Streamlit 还是前台进程 | 测试阶段保持窗口开启；正式上线后配置 Windows 服务或受控进程守护 |

PowerShell 默认的红色错误文字在深蓝背景上不清晰时，可仅对当前窗口改为白色：

```powershell
$Host.PrivateData.ErrorForegroundColor = 'White'
```

这只改变显示颜色，不会修复或隐藏错误。

## 8. SQL Server 权限配置原则

服务器级 `LOGIN` 与数据库级 `USER` 是两层对象。已经创建登录名，不代表它已自动拥有每个数据库的权限。DBA 需在目标数据库中完成用户映射。

生产环境推荐只对已批准的报表视图或对象授权：

```sql
USE [ekp_dyy_test];
CREATE USER [report_export_reader] FOR LOGIN [report_export_reader];
GRANT SELECT ON OBJECT::dbo.v_approved_report TO [report_export_reader];
```

仅在隔离的测试数据库中，经 DBA 批准后才可一次性授予所有用户表/视图的只读权限：

```sql
USE [ekp_dyy_test];
CREATE USER [report_export_reader] FOR LOGIN [report_export_reader];
ALTER ROLE [db_datareader] ADD MEMBER [report_export_reader];
```

`db_datareader` 的读取范围较大，不建议用于正式业务库。不得向应用账号授予 `sysadmin`、`db_owner`、`db_datawriter`、`INSERT`、`UPDATE`、`DELETE`、`ALTER`、`CONTROL` 或不必要的 `EXECUTE`。

## 9. 上线前检查清单

1. `secrets.toml` 的 TOML/UTF-8 独立验证通过。
2. `python -c "import pyodbc; print(pyodbc.drivers())"` 与 `driver` 配置完全一致。
3. 使用专用只读账号在 SSMS 和验证脚本中都能访问同一目标库。
4. 选择的报表与目标库实际表/视图匹配，不在 OA 库使用 `employee_list`。
5. `allowed_logins` 与 SQL Server 返回的登录名完全一致。
6. 只读账号不属于任何高权限角色，只能执行已批准的 `SELECT`。
7. 小日期范围的查询预览、50 行分页和 Excel 下载均通过。
8. 浏览器强制刷新后页面无旧静态资源错误。
9. 密码文件、`audit.db`、导出 Excel、日志、`.venv` 和 `.git` 没有包含在交付 ZIP 中。
10. 向用户只开放 8501，不开放 1433；正式运行采用 Windows 服务或受控守护方式。

## 10. 上线边界

- 不向用户分发 `.streamlit\secrets.toml`；其中含数据库密码。
- 用户只访问 `http://服务器地址:8501`。
- 用户通过业务模块、中文条件和中文字段完成查询；多表关联由后台固定只读 SQL 处理，不向用户开放任意选表、任意关联或 SQL 输入。
- 首版不要求用户登录或填写姓名工号；查询审计统一标记为“匿名访问”。后续如需个人级审计，应接入公司统一身份认证。
- V3 页面分页每页最多 50 行，不再仅预览 100 行；Excel 导出仍受 `max_export_rows` 与 Excel 工作表行数上限约束。
