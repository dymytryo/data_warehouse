# Snowflake zero-copy cloning and storage costs

## What zero-copy cloning does

A zero-copy clone is a writable snapshot of a standard Snowflake table, schema,
or database. For standard tables, Snowflake creates the clone by adding metadata
references to existing micro-partitions. It does not make a second physical
copy of the table data.

```sql
CREATE TABLE <target_table> CLONE <source_table>;

CREATE SCHEMA <target_schema> CLONE <source_schema>;

CREATE DATABASE <target_database> CLONE <source_database>;
```

`CREATE ... CLONE` is handled in the cloud-services layer and does not require
a running warehouse. A warehouse is required when the source or clone is
queried or modified.

The source and clone are independent logical objects:

- Each has its own metadata and lifecycle.
- An `INSERT`, `UPDATE`, or `DELETE` on one does not change the other.
- At creation, both objects can point to the same physical micro-partitions.
- As either object changes, Snowflake creates new micro-partitions for that
  object.

## How micro-partition sharing works

Snowflake micro-partitions are immutable. Existing partitions are not edited in
place. A data change produces new or replacement partitions, and Snowflake
updates the table metadata to point to the correct set.

The following diagrams use simplified partition identifiers. A real statement
can affect many micro-partitions.

### 1. When the clone is created

```text
Source table metadata ----+
                          +----> [MP-1] [MP-2] [MP-3]
Clone table metadata -----+            shared once
```

Both objects point to `MP-1`, `MP-2`, and `MP-3`. The clone adds metadata, but
it adds no new data micro-partitions. The initial table data is stored once, so
creating the clone does not double the table-storage cost.

This is why cloning is normally fast. A very large object can still take time
when Snowflake must create metadata references for millions of
micro-partitions.

### 2. When the source changes

Assume an update changes rows stored in `MP-3`. Snowflake writes the changed
version to a new partition, `MP-4`, and changes only the source metadata.

```text
Source table --> [MP-1] [MP-2] [MP-4 source version]
Clone table  --> [MP-1] [MP-2] [MP-3 original version]
                 shared shared

Physical partitions still required: MP-1, MP-2, MP-3, MP-4
```

`MP-3` is no longer part of the current source table, but it cannot be removed
while the clone still references it. The source and clone continue to share the
unchanged partitions.

The source change adds storage for `MP-4`; it does not produce a new full copy
of the table.

### 3. When the clone changes

Now assume an update changes clone rows stored in `MP-2`. Snowflake writes a
clone-specific replacement, `MP-5`, while the source continues to reference
`MP-2`.

```text
Source table --> [MP-1] [MP-2 source version] [MP-4 source version]
Clone table  --> [MP-1] [MP-5 clone version]  [MP-3 clone version]
                 shared

Physical partitions still required: MP-1, MP-2, MP-3, MP-4, MP-5
```

The clone change adds storage for `MP-5`. Only `MP-1` remains shared in this
simplified example.

### 4. How the storage cost grows

| Point in time | Current source references | Current clone references | Physical partitions still required | New data partitions since cloning |
| --- | --- | --- | --- | ---: |
| Clone created | `MP-1, MP-2, MP-3` | `MP-1, MP-2, MP-3` | `MP-1, MP-2, MP-3` | 0 |
| Source changes `MP-3` | `MP-1, MP-2, MP-4` | `MP-1, MP-2, MP-3` | `MP-1, MP-2, MP-3, MP-4` | 1 |
| Clone changes `MP-2` | `MP-1, MP-2, MP-4` | `MP-1, MP-5, MP-3` | `MP-1, MP-2, MP-3, MP-4, MP-5` | 2 |

These counts illustrate divergence only. Snowflake storage charges are based on
compressed bytes retained, not on the number of micro-partitions.

Storage is based on the physical partitions that must still exist, not on
`full source size + full clone size`. Shared bytes are stored once. New storage
is introduced as DML creates partitions owned by the source or clone.

Old partitions can also remain billable for Continuous Data Protection:

- Time Travel retains changed and deleted data for the configured retention
  period.
- Permanent-table data then enters Fail-safe.
- If a clone still points to bytes that would otherwise be released, those
  bytes remain retained for the clone.
- `SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS` separates `ACTIVE_BYTES`,
  `TIME_TRAVEL_BYTES`, `FAILSAFE_BYTES`, and `RETAINED_FOR_CLONE_BYTES`.

Zero-copy therefore means no initial physical duplication. It does not mean
that a long-lived clone with frequent changes has no storage cost.

## Table cloning example

### 1. Create the source table

```sql
USE ROLE SYSADMIN;

CREATE DATABASE IF NOT EXISTS FINANCE_SANDBOX;
CREATE SCHEMA IF NOT EXISTS FINANCE_SANDBOX.CLONE_DEMO;

CREATE OR REPLACE TABLE
    FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_SOURCE AS
SELECT
    COLUMN1::DATE AS FISCAL_MONTH,
    COLUMN2::VARCHAR AS DEPARTMENT,
    COLUMN3::NUMBER AS BUDGETED_HEADCOUNT
FROM VALUES
    ('2026-07-01', 'Engineering', 125),
    ('2026-07-01', 'Finance', 32),
    ('2026-07-01', 'People', 28);
```

### 2. Create the clone

```sql
CREATE OR REPLACE TABLE
    FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_CLONE
CLONE FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_SOURCE;
```

Verify the initial state:

```sql
SELECT
    'SOURCE' AS OBJECT_NAME,
    COUNT(*) AS ROW_COUNT,
    SUM(BUDGETED_HEADCOUNT) AS TOTAL_HEADCOUNT
FROM FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_SOURCE

UNION ALL

SELECT
    'CLONE' AS OBJECT_NAME,
    COUNT(*) AS ROW_COUNT,
    SUM(BUDGETED_HEADCOUNT) AS TOTAL_HEADCOUNT
FROM FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_CLONE
ORDER BY OBJECT_NAME DESC;
```

| OBJECT_NAME | ROW_COUNT | TOTAL_HEADCOUNT |
| --- | ---: | ---: |
| `SOURCE` | 3 | 185 |
| `CLONE` | 3 | 185 |

The matching query result confirms the logical snapshot. The metadata pointers,
not this query, are what make it zero-copy.

### 3. Change the source

```sql
UPDATE FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_SOURCE
SET BUDGETED_HEADCOUNT = 126
WHERE DEPARTMENT = 'Engineering';
```

| number of rows updated |
| ---: |
| 1 |

```sql
SELECT
    'SOURCE' AS OBJECT_NAME,
    BUDGETED_HEADCOUNT
FROM FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_SOURCE
WHERE DEPARTMENT = 'Engineering'

UNION ALL

SELECT
    'CLONE' AS OBJECT_NAME,
    BUDGETED_HEADCOUNT
FROM FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_CLONE
WHERE DEPARTMENT = 'Engineering'
ORDER BY OBJECT_NAME DESC;
```

| OBJECT_NAME | BUDGETED_HEADCOUNT |
| --- | ---: |
| `SOURCE` | 126 |
| `CLONE` | 125 |

The source points to replacement partition data. The clone retains the version
that existed when it was created.

### 4. Change the clone

```sql
UPDATE FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_CLONE
SET BUDGETED_HEADCOUNT = 35
WHERE DEPARTMENT = 'Finance';
```

| number of rows updated |
| ---: |
| 1 |

```sql
SELECT
    'SOURCE' AS OBJECT_NAME,
    DEPARTMENT,
    BUDGETED_HEADCOUNT
FROM FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_SOURCE

UNION ALL

SELECT
    'CLONE' AS OBJECT_NAME,
    DEPARTMENT,
    BUDGETED_HEADCOUNT
FROM FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_CLONE
ORDER BY DEPARTMENT, OBJECT_NAME;
```

| OBJECT_NAME | DEPARTMENT | BUDGETED_HEADCOUNT |
| --- | --- | ---: |
| `CLONE` | Engineering | 125 |
| `SOURCE` | Engineering | 126 |
| `CLONE` | Finance | 35 |
| `SOURCE` | Finance | 32 |
| `CLONE` | People | 28 |
| `SOURCE` | People | 28 |

Both objects are writable and independent. The unchanged People row remains
logically identical, while the changed rows belong to different partition
versions.

## Combine zero-copy cloning with Time Travel

Time Travel selects a retained historical version of an object. `CLONE` turns
that selected version into a new writable object without performing a full
physical copy.

```text
Before UPDATE:       source --> [MP-1] [MP-2] [MP-4]
                                  |
                                  +--> historical clone

After UPDATE:        source --> [new current micro-partitions]
Historical clone:             [MP-1] [MP-2] [MP-4]
```

The historical clone initially references micro-partitions that Snowflake
already retained for Time Travel. If the clone remains after the source no
longer needs those versions, its references can keep those bytes in storage.
Changes to the historical clone create additional clone-owned partitions in the
same way as a current-state clone.

### 1. Run an update and capture its query ID

```sql
UPDATE FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_SOURCE
SET BUDGETED_HEADCOUNT = 0;
```

| number of rows updated |
| ---: |
| 3 |

Run this immediately after the update:

```sql
SELECT LAST_QUERY_ID() AS BAD_UPDATE_QUERY_ID;
```

| BAD_UPDATE_QUERY_ID |
| --- |
| `<query ID returned for the UPDATE>` |

### 2. Clone the table from before the update completed

```sql
CREATE OR REPLACE TABLE
    FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_BEFORE_UPDATE
CLONE FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_SOURCE
BEFORE (STATEMENT => '<paste the UPDATE query ID here>');
```

`BEFORE` excludes this update. With a statement ID, Snowflake selects the point
immediately before the statement completed. Concurrent changes committed while
the statement ran can still be included.

### 3. Compare the current source with the historical clone

```sql
SELECT
    'CURRENT SOURCE' AS OBJECT_NAME,
    SUM(BUDGETED_HEADCOUNT) AS TOTAL_HEADCOUNT
FROM FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_SOURCE

UNION ALL

SELECT
    'HISTORICAL CLONE' AS OBJECT_NAME,
    SUM(BUDGETED_HEADCOUNT) AS TOTAL_HEADCOUNT
FROM FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_BEFORE_UPDATE
ORDER BY OBJECT_NAME;
```

| OBJECT_NAME | TOTAL_HEADCOUNT |
| --- | ---: |
| `CURRENT SOURCE` | 0 |
| `HISTORICAL CLONE` | 186 |

The historical clone contains the source state after the earlier Engineering
change and before the update that set all values to zero.

### Historical boundaries

| Boundary | Example | State selected |
| --- | --- | --- |
| Statement | `BEFORE (STATEMENT => '<query_id>')` | Immediately before the identified statement completed |
| Timestamp | `AT (TIMESTAMP => DATEADD(hour, -1, CURRENT_TIMESTAMP())::TIMESTAMP_TZ)` | At the calculated timestamp |
| Offset | `AT (OFFSET => -3600)` | One hour before the current time |

`AT` includes changes at the selected boundary. The historical state must still
be within the source object's Time Travel retention period. A statement query
ID can be used for up to 14 days; use a retained timestamp for an older point.

## Schema and database clones

Cloning is recursive for schemas and databases:

- A schema clone includes the objects contained in the source schema.
- A database clone includes its schemas and their contained objects.
- Only objects accessible to the cloning role are included.

Syntax templates:

```sql
CREATE SCHEMA <target_schema>
CLONE <source_schema>;

CREATE DATABASE <target_database>
CLONE <source_database>
AT (OFFSET => -3600);
```

These commands use the same micro-partition sharing model as a table clone.

| Area | Clone behavior |
| --- | --- |
| Historical container clone | Fails if a child table lacks the requested retained history. `IGNORE TABLES WITH INSUFFICIENT DATA RETENTION` skips those tables. |
| External tables | Not cloned with a database or schema. |
| Hybrid tables | A database clone physically copies hybrid-table row-store data and uses compute. A schema clone cannot include hybrid tables; `IGNORE HYBRID TABLES` skips them. |
| Internal named stages | Omitted unless `INCLUDE INTERNAL STAGES` is specified. With a directory table, registered files are copied and can incur charges; without one, the cloned stage is empty. |
| Pipes | Pipes referencing internal stages are not cloned. Pipes referencing external stages are cloned but initially paused or stopped. |
| Table grants | `COPY GRANTS` copies explicit privileges except `OWNERSHIP`. Without it, explicit source grants are not copied. |
| Automatic Clustering | Starts suspended on a cloned table. |
| Load history | The source table's load history is not copied. |

## Cleanup

```sql
DROP TABLE IF EXISTS
    FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_BEFORE_UPDATE;

DROP TABLE IF EXISTS
    FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_CLONE;

DROP TABLE IF EXISTS
    FINANCE_SANDBOX.CLONE_DEMO.WORKFORCE_BUDGET_SOURCE;
```
