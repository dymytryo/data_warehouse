SELECT
    'snowflake' AS catalog,
    table_schema,
    table_name
FROM
    snowflake.information_schema.tables
WHERE
    True
    AND table_schema LIKE '_%'
    AND table_type = 'BASE TABLE'
UNION ALL
SELECT
    'snowflake_pii' AS catalog,
    table_schema,
    table_name
FROM
    snowflake_pii.information_schema.tables
WHERE
    True
    AND table_schema LIKE '_%'
    AND table_type = 'BASE TABLE'
