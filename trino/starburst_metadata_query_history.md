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
{{
    config(
        materialized='incremental',
        unique_key ='query_id',
        incremental_strategy='delete+insert'
    )
}}

SELECT
    query_id,
    dbt.name AS model_name,
    dbt.materialization,
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
        ELSE json_extract_scalar(failure_info, '$.message') END AS error_message,
        total_rows,
        total_bytes,
        CAST(REPLACE(CAST(create_time AT TIME ZONE 'America/Los_Angeles' AS VARCHAR), ' America/Los_Angeles', '') AS TIMESTAMP) AS create_time_pt,
        CAST(REPLACE(CAST(end_time AT TIME ZONE 'America/Los_Angeles' AS VARCHAR), ' America/Los_Angeles', '') AS TIMESTAMP)    AS end_time_pt,
        q.execution_time,
        q.planning_time,
        q.query_state,
        q.query
        --user_agent,
        --source,
FROM
    starburst_metadb_admin.public.completed_queries q
JOIN
    {{ ref('dbt_run_results') }} dbt
    USING (query_id)
WHERE
    True
    AND usr = 'prod_user'
    -- AND query NOT LIKE 'EXECUTE%'
    AND create_time >= DATE '2025-08-01'
    {% if is_incremental() %}
      AND create_time > CURRENT_DATE - INTERVAL '2' DAY
    {% endif %}
```
Next, aggregate to get metrics: 
```sql
SELECT
    DATE_TRUNC('day', create_time) AS  run_date,
    COUNT_IF(query_state = 'FINISHED')*100.00/COUNT(*) AS etl_success_rate,
    COUNT_IF(query_state = 'FINISHED') AS successful_queries,
    COUNT_IF(query_state = 'FAILED') AS failed_etl_queries,
    COUNT(*) AS failed_queries,
    ARRAY_AGG(DISTINCT error_message)
FROM
    starburst_query_history -- this is the incremental import created above
```
# Documentation
```
version: 2

models:
  - name: starburst_query_history
    description: >
      Incremental log of Starburst/Trino completed queries joined to dbt_run_results by
      query_id; standardizes error messages and surfaces execution metrics for the dbt
      service user.
    meta:
      owner: data-platform
    config:
      +tags: ["observability", "starburst", "dbt"]
    columns:
      - name: query_id
        description: "Warehouse query identifier; join key to dbt_run_results."
        tests:
          - not_null
          - unique

      - name: model_name
        description: "dbt node name associated with the query (from dbt_run_results.name)."
        tests:
          - not_null

      - name: materialization
        description: "dbt materialization of the node that issued the query."
        tests:
          - accepted_values:
              values: ["table", "view", "incremental", "snapshot", "seed", "test", "operation", "analysis"]
              severity: warn

      - name: user
        description: "Warehouse user that ran the query (filtered to sa_dp_enterprise_prod@hq.bill.com)."

      - name: full_error_message
        description: "Raw engine failure_info payload from Starburst/Trino."

      - name: error_message
        description: "Normalized error label derived from failure_info.message patterns."

      - name: total_rows
        description: "Total rows reported by Starburst for the query."

      - name: total_bytes
        description: "Total bytes reported by Starburst for the query."

      - name: create_time_pt
        description: "Query start timestamp converted to America/Los_Angeles."

      - name: end_time_pt
        description: "Query end timestamp converted to America/Los_Angeles."

      - name: execution_time
        description: "Execution duration reported by Starburst."

      - name: planning_time
        description: "Planning duration reported by Starburst."

      - name: query_state
        description: "Final state of the query."

      - name: query
        description: "Submitted SQL text."

    tests:
      - relationships:
          to: ref('dbt_run_results')
          field: query_id
          to_field: query_id
```
