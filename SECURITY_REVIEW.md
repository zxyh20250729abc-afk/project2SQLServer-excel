# 安全审查结论

审查范围：`project2SQLServer导入excel系统` MVP 源代码、配置样例和交付机制。审查日期：2026-07-22。

## 结论

在按本项目的只读 SQL 校验、固定报表模板和 DBA 最小权限账号配置后，应用对 **SQL Server 的唯一业务操作是 SELECT 查询**。应用不会执行 INSERT、UPDATE、DELETE、MERGE、DDL、存储过程或事务提交。

无法仅依靠 Python 代码绝对阻止拥有高权限的数据库账号写入。因此“不可修改数据”的强制保障来自数据库账号权限：必须使用独立账号，且只授权指定视图的 SELECT。

## 已实施控制

- 所有报表 SQL 固定于 `reports.py`；界面不接受任意 SQL。
- 每个 SQL 模板在执行前通过 `validate_read_only_sql`，仅允许单条 SELECT，并拒绝写入、DDL、执行权限及管理关键字。
- 所有用户条件通过 pyodbc `?` 参数绑定，禁止字符串拼接 SQL。
- 连接串指定 `ApplicationIntent=ReadOnly`；这是路由提示，不替代数据库权限。
- SQL Server 模式要求配置 `allowed_logins` 白名单；每次建立连接均通过只读 SELECT 检查实际登录名和 `sysadmin`、`db_owner`、`db_datawriter` 角色。未知账号或高权限账号会被阻止，不能查询或导出。
- 凭据仅允许存放在 `.streamlit/secrets.toml` 或部署环境变量中；该文件已被 `.gitignore` 排除。
- 导出审计日志写入本地 SQLite `audit.db`，不写入 SQL Server 业务表。
- 发布脚本排除密钥、虚拟环境、日志、审计库和导出文件，并提供 SHA-256 清单。

## 残余风险与上线条件

| 风险 | 控制/上线条件 |
|---|---|
| 只读应用账号被误授予写权限 | DBA 执行权限核验脚本；禁止 `db_owner`、`db_datawriter`、`sysadmin`。 |
| 维护者修改报表 SQL | 代码审查必须检查只读校验、参数绑定和视图来源；运行自动测试。 |
| 密钥泄露 | 不提交密钥；使用部署平台密钥管理；泄露后立即轮换账号密码。 |
| 导出敏感字段 | 仅通过 DBA/业务批准的视图暴露字段；不要直接访问原始业务表。 |
| 大范围查询影响性能 | 31 天日期上限、查询超时、按日期字段索引和小范围上线验证。 |

## 审查限制

当前环境未提供真实 SQL Server 及只读账号，因此无法完成真实数据库权限和网络连通性验证。该验证必须由接收方在目标环境按照 `docs/REAL_SQLSERVER_VALIDATION.md` 完成。
