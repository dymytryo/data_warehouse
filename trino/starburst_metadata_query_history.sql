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
