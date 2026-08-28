`SOS` - Search Optimization Service from Snowflake (managed service)
Builds and maintains a separate search access path mapping column values to the exact micro-partitions that hold them.
A point lookup then jumps straight into those few partitions instead of scanning the whole table.
Great for: *high-cardinality* columns, selective equality/IN/substring lookups
Useless for: *low-cardinality* columns, or filters already handled by clustering/pruning, or queries returning a large fraction of the table.

Adding search optimization service
```sql
ALTER TABLE <database>.<schema>.<table> ADD SEARCH OPTIMIZATION ON EQUALITY(<column>);
```
You can check which tables have this turned on:
```sql
SHOW TABLES LIKE '%<search-criteria>$'
```
In the output, you will get a column `search_optimization` = `ON`

This is how to check on which of the columns the search optimization service is enabled:
```sql
DESCRIBE SEARCH OPTIMIZATION ON <database>.<schema>.<table>;
```
method = 'EQUALITY'
target = '<column_name>' 

Check the costs:
```sql
SELECT SYSTEM$ESTIMATE_SEARCH_OPTIMIZATION_COSTS(<table>)
```
# Methods
`EQUALITY` -> `col=x`, `col IN (...)`
`SUBSTRING` -> `col LIKE '%x%'`, `REGEXP`
`FULL_TEXT` -> `SEARCH()`
`GEO` -> `ST_*`

# Check for cardinality
SOS pays off when `col` = `x` returns a tiny fraction of a table (<~1%)
-> Low: up to ~1,000 distinct (booleans, status codes, GL accounts, country).
-> Medium: ~1,000 to ~100,000.
-> High: ~100,000 to millions; "very high" near-unique (UUIDs, PKs, emails).
~~~sql
SELECT
  COUNT(*) AS n,
APPROX_COUNT_DISTINCT (uuid) AS d,
COUNT(*) / NULLIF(APPROX_COUNT_DISTINCT(uuid), 0) AS rows_per_value
FROM
  <database>.<schema>.<table>;
~~~
