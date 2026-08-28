# Database indexes

An index is a separately maintained lookup structure that helps a database find
rows without scanning every row in a table. It stores selected key values and a
way to locate the corresponding table rows.

Indexes are central to online transaction processing (OLTP), where applications
run many short, concurrent transactions that read or change a few rows at a
time. They trade additional storage and write work for faster selective reads.
The Structured Query Language (SQL) examples use PostgreSQL; the underlying
design decisions apply broadly, but exact index features vary by database
engine.

## How an index works

Without an index, the engine usually checks each table page until it finds every
matching row. With an index, the optimizer can traverse a smaller structure to
find row locations and then retrieve only the matching rows.

```text
Read query
    |
    v
Query optimizer
    |
    +-- table scan ------> read table pages ------> matching rows
    |
    +-- index traversal -> matching row locations -> fetch table rows

Write
    |
    +-- change table row
    +-- update every affected index
```

The optimizer chooses the access path. Creating an index makes another path
available; it does not force every query to use it. A table scan can still be
cheaper for a small table or a query that returns much of the table.

## B-tree mental model

A B-tree is the common default index. It keeps keys sorted in pages arranged as
a shallow tree:

```text
                    root page
                 [500 | 1000]
                  /    |    \
          branch      branch      branch
             |           |           |
        leaf pages   leaf pages   leaf pages
       key -> row    key -> row    key -> row
```

An equality lookup descends to the relevant leaf page. A range lookup finds its
starting leaf and walks adjacent entries. This normally reads far fewer pages
than scanning a large table. B-trees support equality, ranges, and ordering.
Anchored prefix searches can also use them when the engine's collation and
operator configuration support it; leading-wildcard searches normally cannot.

## State change and cost

| State | Reads | Writes | Storage and compute |
| --- | --- | --- | --- |
| Before | Selective queries may scan the table | Change the table only | Table storage only |
| Build | Existing rows are read and index entries are sorted and written | Writes may block or slow, depending on the engine and build option | Temporary build work plus new index storage |
| After | The optimizer can use the index for matching queries | Every relevant insert, update, and delete also maintains the index | Permanent index storage, cache use, and maintenance work |

An index copies its key and included values into another structure. Those pages
need the same encryption, backup, and access-control protection as table data;
an index is not a new permission boundary. Wide keys and many indexes increase
storage, memory pressure, write-ahead logging, and write latency.

## Terms that drive index value

| Term | Meaning | Why it matters |
| --- | --- | --- |
| Table cardinality | Number of rows in the table | Larger tables make avoidable scans more expensive |
| Column cardinality | Number of distinct values in a column | Distinct keys can narrow equality lookups |
| Selectivity | Fraction of rows matched by a predicate | An index is most attractive when the query needs a small fraction of the table |

High cardinality does not make a column worth indexing by itself. The workload
must actually filter, join, or order by that column. A low-cardinality status can
still be useful in a partial index when one rare status is queried frequently.

## Common index shapes

| Shape | Purpose | Main caution |
| --- | --- | --- |
| Primary or unique | Enforce uniqueness and provide a lookup path | Do not duplicate the index created by the constraint |
| Single-column | Accelerate one common predicate or join key | Weak when the predicate returns much of the table |
| Composite | Match a query that uses multiple columns together | Column order controls which scans are efficient |
| Covering | Store output columns with the search keys | Included values increase index width and write cost |
| Partial or filtered | Index only rows matching a fixed condition | The query must imply the same condition |
| Expression | Index a computed value such as a normalized email | The query must use a matching expression |
| Hash | Support equality lookup | Does not support ranges or ordering |
| Specialized | Support text, spatial, array, or other engine-specific searches | Choose one only for its supported operators |
| Clustered | Store or organize table rows by the index key | A table can have only one physical clustering order |
| Secondary or nonclustered | Store keys and row locators separately from table rows | Matching rows may still require table-page reads |

Clustered and secondary implementations differ by engine. PostgreSQL's ordinary
indexes are secondary. Its `CLUSTER` command performs a one-time table rewrite
and does not keep later changes physically ordered.

## Composite and covering indexes

A composite B-tree is ordered by the first key, then by the second key within
each first-key value:

```text
(customer_id, ordered_at)

customer 501: Jan 02, Jan 15, Feb 08
customer 502: Jan 03, Feb 01, Feb 20
```

This order efficiently supports customer-only and customer-plus-date searches.
A date-only search usually cannot bound the scan efficiently because the leading
customer key is unknown. Some engines have skip-scan optimizations, but they do
not replace choosing an order that matches the normal query shape.

A covering index contains everything a query needs:

```text
search keys:       customer_id, ordered_at
included payload:  status, total_amount
```

Included columns can be returned from the index but do not guide the search or
participate in uniqueness. An engine may perform an index-only scan when the
index contains every required value and its visibility rules allow it.

## Example: recent orders for one customer

The application repeatedly requests a customer's recent order status. The
complete runnable example is in
[database_indexes_postgresql.sql](database_indexes_postgresql.sql).

```sql
SELECT
    ordered_at,
    status,
    total_amount
FROM database_indexing_orders
WHERE customer_id = 501
  AND ordered_at >= TIMESTAMP '2026-03-01 00:00:00'
ORDER BY ordered_at DESC
LIMIT 3;
```

| ordered_at | status | total_amount |
| --- | --- | ---: |
| 2026-03-11 02:20:00 | CANCELLED | 55.00 |
| 2026-03-10 09:40:00 | PENDING | 45.00 |
| 2026-03-09 17:00:00 | PAID | 35.00 |

The equality predicate comes first, followed by the range and ordering column.
The selected payload columns are included rather than used as search keys:

```sql
CREATE INDEX database_indexing_orders_customer_time_idx
ON database_indexing_orders (
    customer_id,
    ordered_at DESC
)
INCLUDE (
    status,
    total_amount
);
```

The index is well matched to this query, but not automatically to every query on
the table. For example, a search on `ordered_at` alone does not constrain the
leading `customer_id` key.

## Prove that an index helps

Start with the query, not with a column list. The companion script runs the same
`EXPLAIN (ANALYZE, BUFFERS)` statement before and after creating the candidate
index.

1. Capture a frequent or slow query and its representative parameters.
2. Record the baseline plan, elapsed time, returned rows, and logical reads.
3. Choose keys that match its equality, range, join, and ordering conditions.
4. Add payload columns only when avoiding table-row fetches is valuable.
5. Check for indexes already created by constraints or overlapping definitions.
6. Build one candidate in a production-sized test environment.
7. Use the engine's concurrent or online build option for a busy production
   table after understanding its time, resource, and failure behavior.
8. Refresh optimizer statistics when the engine requires it.
9. Compare the plan and read cost, then measure the added write and storage cost.
10. Monitor a representative business cycle and keep the index only when the
    measured workload benefits.

| Plan evidence | What to inspect |
| --- | --- |
| Scan node | Whether the engine chose a sequential, index, bitmap, or index-only scan |
| Index condition | Which predicates actually navigated the index |
| Filter | Which predicates were checked only after candidate rows were found |
| Estimated versus actual rows | Whether optimizer statistics describe the data accurately |
| Buffers | Whether the index reduced page reads |
| Heap fetches | Whether an index-only scan still visited table pages |

`EXPLAIN ANALYZE` executes the statement. Use a disposable environment or a
transaction that is rolled back when analyzing data-changing statements.

Rebuild an index only when corruption, bloat, or measured layout problems
justify it. Do not rebuild blindly on a schedule. Common warning signs in a new
design are an unmatched function or cast, a leading-wildcard search, a predicate
only on a non-leading composite key, low selectivity, or a tiny test dataset.

## Snowflake boundary

Standard Snowflake tables do not use conventional user-created indexes. They use
columnar micro-partitions, pruning, clustering, and optional Search Optimization.
See [Micro-partitions and clustering](../snowflake/reference/micro-partitions-and-clustering.md).
Snowflake [hybrid tables](../snowflake/reference/hybrid-tables.md) use real
primary, constraint, and secondary indexes for operational workloads.
