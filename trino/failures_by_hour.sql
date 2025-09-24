WITH all_failures AS (
  SELECT
      query_id,
      create_time AT TIME ZONE 'America/Los_Angeles' AS create_time_pt
  FROM starburst_metadb_admin.public.completed_queries
  WHERE query_state <> 'FINISHED'
    AND query NOT LIKE 'EXECUTE%'
    AND create_time >= DATE '2025-09-01'
    AND failure_info LIKE '%The optimizer exhausted the time limit of 180000 ms%'
),
counts AS (
  SELECT EXTRACT(HOUR FROM create_time_pt) AS hour_pt,
         COUNT(*) AS n
  FROM all_failures
  GROUP BY 1
)
SELECT h AS hour_pt,
       COALESCE(c.n, 0) AS n
FROM UNNEST(SEQUENCE(0, 23)) AS t(h)
LEFT JOIN counts c ON c.hour_pt = t.h
ORDER BY hour_pt;
