# Snowflake micro-partitions and clustering

## What clustering changes

A clustering key is one or more table columns or expressions that Snowflake
uses to improve how related values are organized across micro-partitions. Better
organization can let Snowflake prune more micro-partitions for recurring,
selective filters and joins.

Clustering is not an index, and it does not make every query faster. It is most
useful when a very large table has important queries that repeatedly use the
same predicates but still scan a large share of the table.

See [Snowflake architecture and micro-partitions](architecture-and-micro-partitions.md)
for the storage and pruning fundamentals.

## Why natural clustering can degrade

Snowflake initially creates micro-partitions according to data load order. If
data arrives in roughly the same order as a common filter, natural clustering
may already provide effective pruning.

Late-arriving data, repeated inserts, and data manipulation language (DML)
changes can spread related values across overlapping micro-partitions. A
selective query may then scan many partitions because their metadata ranges all
contain possible matches.

The following diagram shows the clustering-depth concept. The marker shows
the number of micro-partitions whose key ranges overlap at one value.

```text
Clustering-key value ---------------------------------------------->

High overlap
MP-1  [----------------------]
MP-2  [----------------------]
MP-3  [----------------------]
MP-4  [----------------------]
                   ^ one value falls within four partition ranges

Partial overlap
MP-1  [--------]
MP-2          [--------------]
MP-3          [--------------]
MP-4          [--------------]
                         ^ one value falls within three ranges

Low overlap
MP-1  [--------]
MP-2           [--------]
MP-3                    [--------]
MP-4                             [--------]
       Most values fall within one partition range.
```

At a point in the key range, clustering depth is the number of overlapping
micro-partitions. Snowflake's clustering functions report an average across the
table, not only the local depth shown in the diagram. Lower average depth is
generally better for the same table and candidate key.

## Decide whether clustering is the right technique

Read the Query Profile before changing the table. In the target table's
`TableScan` operator, start with these signals:

| What to inspect | Clustering may help when | Look elsewhere when |
| --- | --- | --- |
| Partitions scanned versus total | A selective filter scans a large share of the table | Only a small fraction is scanned already |
| Bytes scanned and scan time | The table scan dominates execution | Scan work is a minor part of execution |
| Filter after the scan | Many rows are discarded after reading them | The filter is not selective |
| Other operators | The scan is the main bottleneck | Queuing, an exploding join, sorting, or remote spilling dominates |

A table measured in multiple terabytes is a reasonable candidate, but size
alone is not evidence that clustering will help. The query benefit must be
large and frequent enough to justify ongoing maintenance.

A common heuristic says that tables smaller than 1 terabyte (TB) usually do not
need a clustering key because natural clustering is often sufficient. Treat
this as a screening guideline, not a threshold. Query patterns, pruning, the
number of micro-partitions, and the ratio of queries to DML matter more.

## Choose a candidate clustering key

Choose expressions from the workload, not from the table definition alone.

| Candidate | Potential benefit | Main risk |
| --- | --- | --- |
| Frequently filtered date or category | Better pruning for recurring predicates | Very low cardinality may still leave many partitions to scan |
| Frequently used join column | Can reduce scanning before a recurring selective join | It does not fix a join that expands the result dramatically |
| High-cardinality identifier | Supports selective lookups | More expensive to maintain |
| Unique key | Supports point lookups | Maintenance can cost more than the saved query work |
| Expression such as `TO_DATE(transaction_ts)` | Reduces excessive timestamp cardinality while preserving order | Helps only query patterns compatible with the expression |
| Multiple expressions | Supports recurring compound predicates | More expressions increase maintenance complexity |

For a multi-column key, Snowflake generally recommends ordering expressions
from lower to higher cardinality. Workload fit still comes first. Usually stop
at three or four expressions and do not add columns merely because they are
available.

## Establish a comparable query baseline

Choose several representative queries that matter to the workload. Use the
same query text, parameters, warehouse size, and cache procedure before and
after clustering. Disable persisted result reuse during the test:

```sql
ALTER SESSION SET QUERY_TAG = 'clustering_baseline';
ALTER SESSION SET USE_CACHED_RESULT = FALSE;
```

This does not disable the warehouse data cache. Run multiple passes and compare
equivalent warm or cold runs instead of mixing cache conditions.

For each representative query, record elapsed time, bytes scanned, partitions
scanned, partitions total, and the percentage scanned from the warehouse cache.

## Measure candidate clustering

`SYSTEM$CLUSTERING_DEPTH` evaluates the average overlap for the specified
expressions. It can evaluate a candidate before it becomes the table's key.

```sql
SELECT SYSTEM$CLUSTERING_DEPTH(
    'ANALYTICS.PUBLIC.FACT_TRANSACTIONS',
    '(TO_DATE(TRANSACTION_TS))'
) AS CANDIDATE_DEPTH;
```

Record the result rather than applying a universal pass or fail value:

| CANDIDATE_DEPTH |
| ---: |
| `<measured depth>` |

A populated table returns a value of at least `1`. A smaller value is generally
better, but compare the same table and key before and after clustering. Query
performance remains the final test.

`SYSTEM$CLUSTERING_INFORMATION` adds overlap counts, partition counts, warnings,
and the Automatic Clustering implementation used for the table:

```sql
WITH RESULT AS (
    SELECT PARSE_JSON(SYSTEM$CLUSTERING_INFORMATION(
        'ANALYTICS.PUBLIC.FACT_TRANSACTIONS',
        '(TO_DATE(TRANSACTION_TS))'
    )) AS INFO
)
SELECT
    INFO:cluster_by_keys::STRING AS CLUSTER_BY_KEYS,
    INFO:version::STRING AS VERSION,
    INFO:total_partition_count::NUMBER AS TOTAL_PARTITION_COUNT,
    INFO:average_overlaps::FLOAT AS AVERAGE_OVERLAPS,
    INFO:average_depth::FLOAT AS AVERAGE_DEPTH,
    INFO:notes::STRING AS NOTES,
    INFO:clustering_errors::STRING AS CLUSTERING_ERRORS
FROM RESULT;
```

Record the common fields:

| CLUSTER_BY_KEYS | VERSION | TOTAL_PARTITION_COUNT | AVERAGE_OVERLAPS | AVERAGE_DEPTH | NOTES | CLUSTERING_ERRORS |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `<candidate key>` | `CLASSIC` or `OPTIMA` | `<partitions>` | `<overlaps>` | `<depth>` | `<warnings or null>` | `<errors or null>` |

Snowflake can use different Automatic Clustering implementations. Check
`VERSION` instead of assuming that every table exposes the same detailed
metrics. For tables with more than two million micro-partitions, this function
samples two million partitions.

## Estimate cost before enabling clustering

Automatic Clustering uses Snowflake-managed compute rather than a virtual
warehouse selected by the user. It consumes credits, so estimate the initial
and maintenance work before changing a multi-terabyte table:

```sql
WITH RESULT AS (
    SELECT PARSE_JSON(SYSTEM$ESTIMATE_AUTOMATIC_CLUSTERING_COSTS(
        'ANALYTICS.PUBLIC.FACT_TRANSACTIONS',
        '(TO_DATE(TRANSACTION_TS))'
    )) AS ESTIMATE
)
SELECT
    ESTIMATE:clusteringKey::STRING AS CLUSTERING_KEY,
    ESTIMATE:initial.value::FLOAT AS INITIAL_CREDITS,
    ESTIMATE:maintenance.value::FLOAT AS MAINTENANCE_CREDITS_PER_DAY
FROM RESULT;
```

Output shape:

| CLUSTERING_KEY | INITIAL_CREDITS | MAINTENANCE_CREDITS_PER_DAY |
| --- | ---: | ---: |
| `<candidate key>` | `<estimated credits>` | `<estimated credits or null>` |

The maintenance estimate can be absent when the table does not have enough DML
history. Run the estimate more than once. It is directional, and actual cost
can differ substantially.

## Define the clustering key

The general syntax is:

```sql
ALTER TABLE <table_name>
    CLUSTER BY (<column_or_expression> [, ...]);
```

For the transactions example:

```sql
ALTER TABLE ANALYTICS.PUBLIC.FACT_TRANSACTIONS
    CLUSTER BY (TO_DATE(TRANSACTION_TS));
```

Defining the key updates the table metadata, but it does not immediately
rewrite every micro-partition. Snowflake monitors the table and uses Automatic
Clustering only when it determines that reclustering work would be beneficial.

| State | Physical behavior | Cost effect |
| --- | --- | --- |
| Before | Existing micro-partitions remain active, including overlapping ranges | Existing table storage |
| Key defined | Table metadata records the clustering expression | No immediate full-table rewrite |
| Reclustering | Snowflake-managed resources write better-organized replacement micro-partitions | Automatic Clustering credits |
| After | Replacements become current; original partitions are marked deleted | Temporary added storage during Time Travel and, for permanent tables, Fail-safe |

Frequent DML can repeatedly create poorly organized micro-partitions and raise
maintenance cost. Clustering changes physical organization, not table rows,
privileges, masking policies, or row access policies.

## Example: evaluate a multi-terabyte transactions table

Assume `ANALYTICS.PUBLIC.FACT_TRANSACTIONS` is several terabytes and important
queries repeatedly filter narrow transaction-date ranges.

1. **Confirm the bottleneck.** Capture Query Profile data for several important
   queries. Continue only if selective predicates scan many partitions and the
   `TableScan` accounts for substantial execution time.
2. **Evaluate the candidate.** Measure depth and clustering information for
   `TO_DATE(TRANSACTION_TS)`. Check `NOTES` for excessive-cardinality warnings.
3. **Estimate the tradeoff.** Compare repeated cost estimates with the query
   frequency and current warehouse cost. High write volume increases ongoing
   clustering work.
4. **Apply a controlled change.** Define the key only after the evidence supports
   it. A [zero-copy clone](zero-copy-cloning.md) can isolate the table change,
   but reclustering the clone still creates new, billable micro-partitions. A
   clone that inherits a clustering key starts with Automatic Clustering
   suspended; resume it intentionally before testing that inherited key.
5. **Wait for physical progress.** A defined key is not proof that the table has
   been reclustered. Recheck clustering information until its metrics stabilize
   enough for a fair test.
6. **Repeat the same workload.** Change the tag, use the same warehouse and cache
   procedure, and rerun the representative queries.

```sql
ALTER SESSION SET QUERY_TAG = 'clustering_after';
```

7. **Measure the ongoing cost.** Account Usage can lag by up to three hours:

```sql
SELECT
    TO_DATE(START_TIME) AS USAGE_DATE,
    VERSION,
    SUM(CREDITS_USED) AS CREDITS_USED,
    SUM(NUM_BYTES_RECLUSTERED) AS BYTES_RECLUSTERED
FROM SNOWFLAKE.ACCOUNT_USAGE.AUTOMATIC_CLUSTERING_HISTORY
WHERE START_TIME >= DATEADD(DAY, -14, CURRENT_TIMESTAMP())
  AND DATABASE_NAME = 'ANALYTICS'
  AND SCHEMA_NAME = 'PUBLIC'
  AND TABLE_NAME = 'FACT_TRANSACTIONS'
GROUP BY 1, 2
ORDER BY 1, 2;
```

Record the daily results:

| USAGE_DATE | VERSION | CREDITS_USED | BYTES_RECLUSTERED |
| --- | --- | ---: | ---: |
| `<date>` | `CLASSIC` or `OPTIMA` | `<credits>` | `<bytes>` |

8. **Make the decision from query and cost evidence.** Use the worksheet for the
   test window, adding query rows when needed:

| Metric | Before | After | Decision evidence |
| --- | ---: | ---: | --- |
| Partitions scanned / total |  |  | Did pruning materially improve? |
| Bytes scanned |  |  | Did less data reach the warehouse? |
| Table-scan share of query time |  |  | Did the original bottleneck shrink? |
| Query elapsed time |  |  | Is the improvement consistent? |
| Query warehouse credits |  |  | How much compute did the workload save? |
| Automatic Clustering credits |  |  | Is maintenance justified? |
| Added retained storage |  |  | Is temporary storage growth acceptable? |

Restore persisted result reuse after the test:

```sql
ALTER SESSION SET USE_CACHED_RESULT = TRUE;
ALTER SESSION UNSET QUERY_TAG;
```

Keep the clustering key only when important queries scan materially fewer
partitions and the saved query work justifies serverless credits and added
retained storage. To pause maintenance without removing the key:

```sql
ALTER TABLE ANALYTICS.PUBLIC.FACT_TRANSACTIONS
    SUSPEND RECLUSTER;
```

Use `RESUME RECLUSTER` to restart Automatic Clustering. If the key should be
abandoned entirely:

```sql
ALTER TABLE ANALYTICS.PUBLIC.FACT_TRANSACTIONS
    DROP CLUSTERING KEY;
```

Dropping the key stops future reclustering. It does not restore the table's
previous physical layout.
