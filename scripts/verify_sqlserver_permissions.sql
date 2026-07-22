/* 只读核验脚本：在目标数据库中以应用只读账号执行。 */
SELECT
    SYSTEM_USER AS login_name,
    USER_NAME() AS database_user,
    DB_NAME() AS database_name;

SELECT permission_name
FROM fn_my_permissions(NULL, 'DATABASE')
ORDER BY permission_name;

SELECT
    OBJECT_SCHEMA_NAME(major_id) AS schema_name,
    OBJECT_NAME(major_id) AS object_name,
    permission_name,
    state_desc
FROM sys.database_permissions
WHERE grantee_principal_id = DATABASE_PRINCIPAL_ID(USER_NAME())
ORDER BY schema_name, object_name, permission_name;
