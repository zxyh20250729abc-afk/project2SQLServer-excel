# 真实 SQL Server 接入与验证

## 1. 交付给接收方

运行 `python scripts/package_release.py` 生成 ZIP。压缩包只包含源代码、文档、配置样例与测试，不包含：

- `.streamlit/secrets.toml` 及任何密码；
- `.venv`、`audit.db`、导出 Excel、日志；
- `.git` 历史。

接收方解压后，先进入解压得到的项目根目录（必须能看到 `requirements.txt`），再执行：

```bash
cd "/解压后的目录/project2SQLServer导入excel系统"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p .streamlit
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```

## 2. DBA 必须完成的权限配置

应用账号必须是专用账号，且只获得当前启用报表所需对象的 `SELECT` 权限。不得使用 `sysadmin`、`db_owner`、`db_datawriter` 或任何具备写权限的共享账号。生产环境建议由 DBA 建立只读报表视图，并只授予这些视图的 `SELECT` 权限。

建议由 DBA 在变更流程中执行并审核类似配置（对象与账号名须替换为实际值）：

```sql
USE [业务数据库];
CREATE USER [report_export_reader] FOR LOGIN [report_export_reader];
GRANT SELECT ON OBJECT::dbo.v_report_contract_amount_summary TO [report_export_reader];
DENY INSERT, UPDATE, DELETE ON OBJECT::dbo.v_report_contract_amount_summary TO [report_export_reader];
```

`CREATE USER` 和 `GRANT` 是 DBA 的一次性权限配置，不属于应用运行步骤；应用本身只执行查询。

## 3. 配置与连通性核验

在 `.streamlit/secrets.toml` 中设置：

```toml
[app]
mode = "sqlserver"
```

填写 `[sqlserver]` 的真实地址、数据库名及只读凭据。`allowed_logins` 必须填写专用只读账号的 `SYSTEM_USER`/`ORIGINAL_LOGIN()` 精确值。若账号不在名单中，或属于 `sysadmin`、`db_owner`、`db_datawriter`，应用会警告并阻止所有查询和导出。

再执行：

```bash
python scripts/verify_sqlserver_connection.py --report employee_list
```

该验证程序只运行 `SELECT SYSTEM_USER`、`SELECT DB_NAME()` 和受控报表的 `SELECT COUNT_BIG`。验证真实业务报表时，将 `employee_list` 替换为相应 key，例如 `finance_claim_detail`、`contract_amount_summary` 或 `contract_stamp_tax_detail`。应用页面额外只读查询固定的字段元数据与最多 200 个部门候选值，仅用于员工测试报表。两者均不写入 SQL Server，也不创建本地审计日志。

然后以相同账号在目标数据库执行 `scripts/verify_sqlserver_permissions.sql`，确认权限结果中没有 `INSERT`、`UPDATE`、`DELETE`、`ALTER`、`CONTROL` 或 `EXECUTE`。

## 4. 上线验证

1. 当前项目包含员工测试报表及 6 份预设业务报表。上线前，DBA 必须逐份确认 `reports.py` 的来源对象、字段口径、日期范围语义和 SELECT 授权；若改为视图，需保持字段含义与报表一致，并保持所有条件使用 `?` 参数。
2. 执行 `pytest -q`，确认基础测试通过。
3. 启动 `streamlit run app.py`，使用一个较小的开始日期、结束日期范围验证分页预览和 Excel 下载；多工作表报表应检查每个工作表。
4. 查询 SQL Server 审计/扩展事件或数据库日志，确认仅出现 `SELECT`。
5. 保留应用本地 `audit.db` 作为导出审计；该文件仅记录导出元数据，不会写入业务数据库。
