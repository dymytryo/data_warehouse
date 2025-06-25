-- Get all schemas in Redshift catalog
SELECT nspname AS schema_name
FROM pg_namespace
ORDER BY schema_name;

-- Get all table names from a given schema
SELECT tablename
FROM pg_tables
WHERE schemaname = 'your_schema_name'
ORDER BY tablename;

-- Get all longest running queries
SELECT
   pid,
   starttime,
   TRIM(user_name) AS user,
   TRIM(query) AS querytxt,
   -- Convert duration from microseconds to HH:MM:SS format
   LPAD(CAST(duration / 1000000 / 3600 AS VARCHAR), 2, '0') || ':' ||
   LPAD(CAST((duration / 1000000 % 3600) / 60 AS VARCHAR), 2, '0') || ':' ||
   LPAD(CAST(duration / 1000000 % 60 AS VARCHAR), 2, '0') AS readable_duration
FROM
   stv_recents -- System Table View
WHERE
   TRUE
   --AND status = 'Running'
ORDER BY
   readable_duration DESC
LIMIT 5;
