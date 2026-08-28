# Snowflake Search Optimization Service (SOS)

## What it is
`SOS` = **Search Optimization Service**, a Snowflake-managed service that builds a search access path mapping values to the micro-partitions that contain them.

This lets highly selective lookups jump directly to relevant micro-partitions instead of scanning broadly.

## Best use cases
**Good for**
- High-cardinality columns: UUIDs, IDs, emails, transaction keys
- Highly selective filters
- Equality / `IN`
- Substring / regex searches
- Full-text search
- Geospatial lookups

**Usually not useful for**
- Low-cardinality columns
- Queries returning a large portion of the table
- Columns already pruned efficiently through natural clustering or clustering keys
- Queries that are already fast

> **Cardinality is a proxy; selectivity is what matters.**  
> A useful rule of thumb: SOS is most attractive when a lookup returns a tiny fraction of the table (often `< ~1%`).

---

## Enable SOS

### Equality
```sql
ALTER TABLE <database>.<schema>.<table>
ADD SEARCH OPTIMIZATION ON EQUALITY(<column>);
```

### Other methods
```text
EQUALITY   -> col = x, col IN (...)
SUBSTRING  -> LIKE, ILIKE, REGEXP, RLIKE
FULL_TEXT  -> SEARCH()
GEO        -> supported ST_* predicates
```

---

## Check whether SOS is enabled

### Table level
```sql
SHOW TABLES LIKE '%<search-criteria>%';
```

Look for:
```text
search_optimization = ON
search_optimization_progress = 100
```

### Column / method level
```sql
DESCRIBE SEARCH OPTIMIZATION
ON <database>.<schema>.<table>;
```

Example:
```text
method = EQUALITY
target = <column_name>
active = TRUE
```

---

## Estimate cost
```sql
SELECT SYSTEM$ESTIMATE_SEARCH_OPTIMIZATION_COSTS(
    '<database>.<schema>.<table>'
);
```

SOS adds:
- Initial build cost
- Storage cost
- Maintenance cost as data changes

---

## Check cardinality
```sql
SELECT
    COUNT(*) AS row_count,
    APPROX_COUNT_DISTINCT(uuid) AS distinct_values,
    COUNT(*) / NULLIF(APPROX_COUNT_DISTINCT(uuid), 0) AS rows_per_value
FROM <database>.<schema>.<table>;
```

### Rough heuristic

| Cardinality | Distinct values | Examples |
|---|---:|---|
| Low | `< ~1K` | boolean, status, country |
| Medium | `~1K–100K` | categories, smaller dimensions |
| High | `100K+` | customer/payment IDs |
| Very high | millions / near-unique | UUIDs, PKs, emails |

---

## Validate that SOS is actually used
After enabling SOS and waiting for:

```text
search_optimization_progress = 100
```

Run the query and inspect **Query Profile**.

Look for:

```text
Search Optimization Access
```

If it appears, Snowflake used the SOS access path.

---

## SOS vs. Clustering

**SOS:** find a needle in a haystack.

```sql
WHERE transaction_uuid = ?
```

**Clustering:** organize the haystack so ranges prune efficiently.

```sql
WHERE transaction_date BETWEEN ... AND ...
```

### Quick decision
SOS is worth testing when:

```text
large table
+ highly selective lookup
+ high-cardinality column
+ weak normal pruning
+ meaningful query latency
= strong SOS candidate
```
