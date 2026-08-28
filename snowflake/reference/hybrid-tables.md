# Snowflake hybrid tables

A hybrid table is a Snowflake table type optimized for low-latency, high-throughput
point reads and writes. It uses row-oriented primary storage, row-level locking,
enforced relational constraints, and indexes. Use it for operational state that
must be read or changed quickly. Standard Snowflake tables remain the default for
large analytical scans and batch transformations.

A point lookup asks for one specific row by an exact key, such as order `1001`.

Hybrid tables are generally available in commercial Amazon Web Services (AWS)
and Microsoft Azure regions. They are not available in Google Cloud, SnowGov
regions, or trial accounts.

## How storage and queries work

Applications use the same Snowflake Structured Query Language (SQL) interface,
cloud-services layer, query engine, and virtual warehouses as analytical
workloads.

```text
Application or SQL client
          |
          v
Snowflake cloud services and optimizer
          |
          v
Virtual warehouse
          |
          +-- point lookup or small write --> row store + indexes
          |
          +-- larger scan -------------> columnar object-storage copy
                                             + warehouse cache
```

Writes go directly to the row store. Snowflake asynchronously copies the data to
columnar object storage, and the optimizer chooses the row store, columnar copy,
or both for each query. Both paths expose one logical table, so a hybrid table can
join directly to standard Snowflake tables without federation.

| Behavior | Hybrid table | Standard table |
| --- | --- | --- |
| Primary layout | Row-oriented, ordered by primary key | Columnar micro-partitions |
| Best workload | Point reads, small writes, operational concurrency | Scans, aggregations, and batch processing |
| Locking | Row-level | Partition- or table-level |
| Primary key | Required and enforced | Optional and normally informational |
| `UNIQUE` and foreign keys | Enforced | Normally informational |
| Lookup optimization | Primary, constraint, and secondary indexes | Pruning, clustering, and optional Search Optimization Service |

## Requirements and important limits

| Area | Behavior |
| --- | --- |
| Database and schema | Must be permanent; hybrid tables cannot be temporary or transient or live in transient containers |
| Warehouse | A running current warehouse is required to create and query the table |
| Default quota | 2 terabytes of active hybrid row-store data per database |
| Default throughput | Approximately 16,000 operations per second per database for a balanced 80% read and 20% write workload |
| Relational constraints | Foreign keys can reference only hybrid tables in the same database; `CHECK` constraints are unsupported |
| Indexed data | Semi-structured, geospatial, and vector columns cannot be index keys; `UUID` is unsupported in the table |
| Recovery | Limited Time Travel; no Fail-safe or `UNDROP` |
| Movement | No replication or data sharing; cloning is limited and physically copies row-store data |
| Pipelines | No streams, Snowpipe, Snowpipe Streaming, dynamic tables, or materialized views |
| Optimization | No clustering keys, Search Optimization Service, Query Acceleration Service, or persisted result cache |

The storage and throughput values are service quotas, not sizing targets. Monitor
the database and ask Snowflake Support about an increase before sustained usage
approaches a quota.

## Permissions

Use a deployment role to create the table and a separate application role for
runtime reads and writes. The deployment role needs `USAGE` on the database,
schema, and warehouse, plus `CREATE HYBRID TABLE` on the schema.

```sql
GRANT USAGE
ON DATABASE <DATABASE>
TO ROLE <DEPLOYMENT_ROLE>;

GRANT USAGE
ON SCHEMA <DATABASE>.APPLICATION
TO ROLE <DEPLOYMENT_ROLE>;

GRANT USAGE
ON WAREHOUSE <WAREHOUSE>
TO ROLE <DEPLOYMENT_ROLE>;

GRANT CREATE HYBRID TABLE
ON SCHEMA <DATABASE>.APPLICATION
TO ROLE <DEPLOYMENT_ROLE>;

GRANT USAGE
ON DATABASE <DATABASE>
TO ROLE <APPLICATION_ROLE>;

GRANT USAGE
ON SCHEMA <DATABASE>.APPLICATION
TO ROLE <APPLICATION_ROLE>;

GRANT USAGE
ON WAREHOUSE <WAREHOUSE>
TO ROLE <APPLICATION_ROLE>;
```

The creating role owns the new table. Grant only the required runtime privileges
to the application role, using `TABLE`, not `HYBRID TABLE`:

```sql
GRANT SELECT, INSERT, UPDATE, DELETE
ON TABLE <DATABASE>.APPLICATION.ORDER_STATUS
TO ROLE <APPLICATION_ROLE>;
```

## Example: operational order status

This table supports fast order lookups and small status updates from an
application while remaining joinable to analytical order history.

See [Database indexes](../../database-indexes/README.md) for the general lookup
model and design tradeoffs. In a Snowflake hybrid table, primary-key, unique, and
foreign-key constraints create indexes automatically. The `INDEX` clause creates
an additional secondary index for another lookup pattern.

```sql
USE ROLE <DEPLOYMENT_ROLE>;
USE WAREHOUSE <WAREHOUSE>;
USE DATABASE <DATABASE>;
USE SCHEMA APPLICATION;

CREATE HYBRID TABLE ORDER_STATUS (
    ORDER_ID NUMBER PRIMARY KEY,
    EXTERNAL_ORDER_ID VARCHAR(64) UNIQUE,
    CUSTOMER_ID NUMBER NOT NULL,
    STATUS VARCHAR(20) NOT NULL,
    TOTAL_AMOUNT NUMBER(12, 2) NOT NULL,
    UPDATED_AT TIMESTAMP_NTZ NOT NULL,
    INDEX IX_ORDER_STATUS_CUSTOMER (CUSTOMER_ID, UPDATED_AT)
        INCLUDE (STATUS, TOTAL_AMOUNT)
);
```

| Table element | What it does | Lookup it supports |
| --- | --- | --- |
| Primary key on `ORDER_ID` | Creates an automatic unique index | Find one order by `ORDER_ID` |
| Unique constraint on `EXTERNAL_ORDER_ID` | Creates another automatic unique index | Find one order by its external identifier |
| Secondary index `IX_ORDER_STATUS_CUSTOMER` on `CUSTOMER_ID` and `UPDATED_AT` | Creates the named lookup path | Find a customer's orders within a time range |
| Included columns `STATUS` and `TOTAL_AMOUNT` | Stores these output values with the secondary-index records; they are not additional lookup keys | Return status and amount without probing the underlying table rows |

```sql
INSERT INTO APPLICATION.ORDER_STATUS (
    ORDER_ID,
    EXTERNAL_ORDER_ID,
    CUSTOMER_ID,
    STATUS,
    TOTAL_AMOUNT,
    UPDATED_AT
)
VALUES
    (1001, 'WEB-9001', 501, 'PENDING', 125.00, '2026-08-28 09:00:00'),
    (1002, 'WEB-9002', 502, 'PAID', 80.00, '2026-08-28 09:05:00');
```

This query filters on both secondary-index keys and selects only included
columns, so Snowflake can answer it from the index without probing the table:

```sql
SELECT
    STATUS,
    TOTAL_AMOUNT
FROM APPLICATION.ORDER_STATUS
WHERE CUSTOMER_ID = 501
  AND UPDATED_AT >= '2026-08-28 00:00:00';
```

| STATUS | TOTAL_AMOUNT |
| --- | ---: |
| PENDING | 125.00 |

The following point lookup uses the automatic primary-key index:

```sql
SELECT
    ORDER_ID,
    STATUS,
    TOTAL_AMOUNT
FROM APPLICATION.ORDER_STATUS
WHERE ORDER_ID = 1001;
```

| ORDER_ID | STATUS | TOTAL_AMOUNT |
| ---: | --- | ---: |
| 1001 | PENDING | 125.00 |

The update locks only the matching row. The state change is explicit:

```text
Before                    Operation                    After commit
1001: PENDING, 09:00  --> UPDATE order 1001       --> 1001: PAID, 09:15
```

```sql
BEGIN;

UPDATE APPLICATION.ORDER_STATUS
SET
    STATUS = 'PAID',
    UPDATED_AT = '2026-08-28 09:15:00'
WHERE ORDER_ID = 1001;

COMMIT;

SELECT
    ORDER_ID,
    STATUS,
    UPDATED_AT
FROM APPLICATION.ORDER_STATUS
WHERE ORDER_ID = 1001;
```

| ORDER_ID | STATUS | UPDATED_AT |
| ---: | --- | --- |
| 1001 | PAID | 2026-08-28 09:15:00 |

The primary key and unique constraint are enforced. A second row with
`ORDER_ID = 1001` fails instead of creating a duplicate.

## Indexes

Add a secondary index only for a repeated lookup path that the automatic
constraint indexes do not cover. Every additional index consumes storage and is
maintained synchronously on writes.

Secondary indexes can accelerate equality, range, `IN`, `BETWEEN`, `STARTSWITH`,
and prefix `LIKE 'value%'` predicates. `ILIKE` does not qualify for index access.
An `INCLUDE` list can turn an index into a covering index for frequently selected
columns that are not predicates.

Verify the example indexes:

```sql
SHOW INDEXES IN TABLE APPLICATION.ORDER_STATUS
    ->> SELECT
            "name",
            "is_unique",
            "table",
            "columns",
            "included_columns"
        FROM $1;
```

| name | is_unique | table | columns | included_columns |
| --- | --- | --- | --- | --- |
| `<system-generated primary index>` | Y | ORDER_STATUS | `[ORDER_ID]` | `[]` |
| `<system-generated unique index>` | Y | ORDER_STATUS | `[EXTERNAL_ORDER_ID]` | `[]` |
| IX_ORDER_STATUS_CUSTOMER | N | ORDER_STATUS | `[CUSTOMER_ID, UPDATED_AT]` | `[STATUS, TOTAL_AMOUNT]` |

System-generated constraint-index names can vary. The columns and uniqueness are
the evidence that the intended access paths exist.

## Transactions and consistency

Hybrid tables use `READ COMMITTED` isolation and support atomic transactions with
hybrid and standard tables. `SELECT ... FOR UPDATE` can explicitly hold row
locks inside a transaction. All hybrid tables referenced by one transaction must
be in the same database; standard tables in that transaction can be in other
databases.

Within a session, reads see that session's latest writes. Changes committed by
other sessions can be slightly stale, normally by less than 100 milliseconds.
Require the latest cross-session writes when correctness needs it:

```sql
ALTER SESSION
SET READ_LATEST_WRITES = TRUE;
```

This adds a few milliseconds of latency. Use `SHOW TRANSACTIONS`, `SHOW LOCKS`,
and `LOCK_WAIT_HISTORY` when diagnosing blocking; Snowflake reports hybrid-table
contention as summarized `ROW` locks.

## Recovery and cloning

Hybrid-table Time Travel supports `AT (TIMESTAMP => ...)`. It does not support
`BEFORE`, `OFFSET`, `STATEMENT`, or `STREAM`, and a dropped hybrid table cannot be
restored with `UNDROP`.

Hybrid tables cannot be cloned individually or through a schema clone. A database
clone can include them, but Snowflake physically copies their row-store data:

```text
Before database clone        Clone operation          After database clone
one row-store copy       --> compute + data copy  --> two independent row-store copies
```

The clone therefore takes time, incurs compute cost, and adds storage in
proportion to the hybrid-table data. See [Zero-copy cloning](zero-copy-cloning.md)
for the exact database and `IGNORE HYBRID TABLES` commands.

## Cost and monitoring

Hybrid-table cost comes from the billed row-store storage and virtual-warehouse
compute. Row storage is more expensive than traditional Snowflake storage and
usually compresses less efficiently. Secondary indexes and physical database
clones increase it. Snowflake does not bill the current-data columnar copy;
historical Time Travel data is billed at the standard storage rate.

Inspect approximate active row-store size in the database's Information Schema:

```sql
SELECT
    NAME,
    ROW_COUNT,
    BYTES
FROM <DATABASE>.INFORMATION_SCHEMA.HYBRID_TABLES
WHERE SCHEMA = 'APPLICATION'
  AND NAME = 'ORDER_STATUS';
```

| NAME | ROW_COUNT | BYTES |
| --- | ---: | ---: |
| ORDER_STATUS | 2 | `<approximate row-store bytes>` |

`ROW_COUNT` and `BYTES` are approximate and can lag while background compaction
updates the metadata.

Short, high-frequency hybrid queries might not appear individually in
`QUERY_HISTORY`. Use `AGGREGATE_QUERY_HISTORY` to check volume and throttling:

```sql
SELECT
    QUERY_PARAMETERIZED_HASH,
    ANY_VALUE(QUERY_TEXT) AS QUERY_TEXT,
    SUM(CALLS) AS EXECUTION_COUNT,
    SUM(HYBRID_TABLE_REQUESTS_THROTTLED_COUNT) AS THROTTLED_COUNT
FROM SNOWFLAKE.ACCOUNT_USAGE.AGGREGATE_QUERY_HISTORY
WHERE WAREHOUSE_NAME = '<WAREHOUSE>'
  AND INTERVAL_START_TIME >= DATEADD('hour', -6, CURRENT_TIMESTAMP())
GROUP BY QUERY_PARAMETERIZED_HASH
ORDER BY EXECUTION_COUNT DESC
LIMIT 10;
```

| QUERY_PARAMETERIZED_HASH | QUERY_TEXT | EXECUTION_COUNT | THROTTLED_COUNT |
| --- | --- | ---: | ---: |
| `<hash>` | `SELECT ... WHERE ORDER_ID = ?` | `<count>` | 0 |

Account Usage can lag by up to three hours, so the latest intervals might be
incomplete. For this check, sustained nonzero throttling requires investigation.
