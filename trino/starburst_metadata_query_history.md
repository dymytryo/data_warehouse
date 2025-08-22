```sql
-- Get last 100 queries that failed due to optimized issue 
-- type=INTERNAL_ERROR
-- name=OPTIMIZER_TIMEOUT
-- message="The optimizer exhausted the time limit of 180000 ms"
SELECT 
    query_id, 
    usr, 
    user_agent,
    query,
    source,
    planning_time,
    failure_info,
    create_time AT TIME ZONE 'America/Los_Angeles' AS create_time_pt
FROM
    starburst_metadb_admin.public.completed_queries
WHERE
    True 
    AND query_state <> 'FINISHED'
    AND query NOT LIKE 'EXECUTE%'
    AND create_time >= DATE '2025-06-20'
    AND failure_info LIKE '%The optimizer exhausted the time limit of 180000 ms%'
ORDER BY 
    create_time DESC
LIMIT 
  100;
```
---
# Query history for a production user
```sql
{{ config(
    materialized='incremental',
    incremental_strategy='append'
) }}

SELECT 
        query_id, 
        usr AS user, 
        failure_info AS full_error_message, 
        CASE
            WHEN json_extract_scalar(failure_info, '$.message') LIKE 'The optimizer exhausted%'
                THEN 'The optimizer exhausted the time limit of 180000 ms'
            WHEN json_extract_scalar(failure_info, '$.message') LIKE 'Could not communicate with the remote task%'
                THEN 'The node may have crashed or be under too much load' 
            WHEN json_extract_scalar(failure_info, '$.message') LIKE 'Error opening Hive split%'
                THEN 'Error opening Hive split' 
            WHEN json_extract_scalar(failure_info, '$.message') LIKE 'Failed to read Parquet file%'
                THEN 'Failed to read Parquet file' 
            WHEN json_extract_scalar(failure_info, '$.message') LIKE 'Failed to get table handle%'
                THEN 'SQL compilation error' 
            WHEN json_extract_scalar(failure_info, '$.message') LIKE 'Failed to commit the transaction%'
                THEN 'Failed to commit the transaction during write' 
            WHEN json_extract_scalar(failure_info, '$.message') LIKE '%Failed analyzing stored view%'
                THEN 'Failed analyzing stored view' 
            WHEN json_extract_scalar(failure_info, '$.message') LIKE '% already exists'
                THEN 'Destination table already exists'   
            WHEN json_extract_scalar(failure_info, '$.message') LIKE 'Failed to open input stream for file%'
                THEN 'Failed to open input stream for file'   
            WHEN json_extract_scalar(failure_info, '$.message') LIKE '%is stale or in invalid state%'
                THEN 'The view is stale or in invalid state'   
            ELSE json_extract_scalar(failure_info, '$.message') 
        END AS error_message,
        total_rows,
        total_bytes,
        CAST(REPLACE(CAST(create_time AT TIME ZONE 'America/Los_Angeles' AS VARCHAR), ' America/Los_Angeles', '') AS TIMESTAMP) AS create_time_pt,
        CAST(REPLACE(CAST(end_time AT TIME ZONE 'America/Los_Angeles' AS VARCHAR), ' America/Los_Angeles', '') AS TIMESTAMP)    AS end_time_pt,
        execution_time,
        planning_time,
        query_state,
        query
FROM
    starburst_metadb_admin.public.completed_queries
WHERE
    True
    AND usr = 'prod_user@prod.com'
    AND query NOT LIKE 'EXECUTE%'
    AND create_time >= DATE '2025-08-15'
    {% if is_incremental() %}
      -- only new records
      AND create_time > (SELECT MAC(create_time) FROM {{ this }})
    {% endif %}
```

