# Snowflake UNDROP Recovery Playbook

## What UNDROP does

`UNDROP` restores a dropped Snowflake object using **Time Travel**. For tables, it restores the most recently dropped version unless a specific dropped object ID is supplied.

```sql
UNDROP TABLE <db>.<schema>.<table>;
UNDROP SCHEMA <db>.<schema>;
UNDROP DATABASE <db>;
```

Recovery with `UNDROP` is possible only while the object is still inside its Time Travel retention window.

---

## Why UNDROP is possible

Snowflake stores table data in **immutable micro-partitions** and uses metadata to map a logical table to the micro-partitions that belong to it.

Dropping a table does **not** immediately erase those micro-partitions from physical storage. The table is logically dropped, while Snowflake retains the dropped table version and its underlying data for the configured Time Travel period.

Conceptually:

```text
Before DROP
TABLE metadata  ──────>  micro-partitions

After DROP
active namespace       X  table no longer visible
                         \
Time Travel metadata  ───> retained table version / micro-partitions

After UNDROP
TABLE metadata  ──────>  retained table version / micro-partitions
```

`UNDROP` therefore does not need to reconstruct the table row-by-row from a backup. It restores the retained object metadata and makes the retained data accessible again.

Once the retention period expires, those retained references/data move out of Time Travel and normal `UNDROP` is no longer available.

---

## 1. Find the dropped table

```sql
SHOW TABLES HISTORY LIKE '<table_name>' IN SCHEMA <db>.<schema>;
```

For example:

```sql
SHOW TABLES HISTORY LIKE 'LEDGER' IN SCHEMA PROD.FINANCE;
```

A simplified version of the output might look like this:

| created_on | name | database_name | schema_name | kind | rows | bytes | owner | retention_time | dropped_on |
|---|---|---|---|---|---:|---:|---|---:|---|
| 2026-06-12 09:14:31 -0500 | LEDGER | PROD | FINANCE | TABLE | 184523991 | 28671938560 | FINANCE_DBT_ROLE | 7 | 2026-09-01 10:42:17 -0500 |

The actual `SHOW TABLES` output contains additional columns. For recovery, pay particular attention to:

- `name` — confirm the object name.
- `database_name` / `schema_name` — confirm the original location.
- `kind` — `TABLE`, `TRANSIENT`, etc.
- `retention_time` — effective Time Travel retention in days.
- `dropped_on` — when the table was dropped. `NULL` means that version is active.

If several rows have the same table name, multiple versions of that table exist.

If the dropped table is no longer returned by `SHOW TABLES HISTORY`, it is no longer available through normal `UNDROP` recovery.

---

## 2. Check the retention configuration

### Account defaults / minimums

Check the account-level default:

```sql
SHOW PARAMETERS LIKE 'DATA_RETENTION_TIME_IN_DAYS' IN ACCOUNT;
```

Check whether the account enforces a minimum retention period:

```sql
SHOW PARAMETERS LIKE 'MIN_DATA_RETENTION_TIME_IN_DAYS' IN ACCOUNT;
```

`DATA_RETENTION_TIME_IN_DAYS` is the default inherited by databases, schemas, and tables unless overridden lower in the hierarchy.

`MIN_DATA_RETENTION_TIME_IN_DAYS` is an account-level floor for supported permanent objects. When it applies, effective retention is:

```text
MAX(DATA_RETENTION_TIME_IN_DAYS, MIN_DATA_RETENTION_TIME_IN_DAYS)
```

### Specific table

For an active table, check its resolved parameter configuration with:

```sql
SHOW PARAMETERS LIKE 'DATA_RETENTION_TIME_IN_DAYS'
IN TABLE <db>.<schema>.<table>;
```

Example:

```sql
SHOW PARAMETERS LIKE 'DATA_RETENTION_TIME_IN_DAYS'
IN TABLE PROD.FINANCE.LEDGER;
```

For a table that is **already dropped**, use the `retention_time` value returned by:

```sql
SHOW TABLES HISTORY LIKE 'LEDGER' IN SCHEMA PROD.FINANCE;
```

If you need to trace inheritance, inspect the schema and database as well:

```sql
SHOW PARAMETERS LIKE 'DATA_RETENTION_TIME_IN_DAYS' IN SCHEMA PROD.FINANCE;
SHOW PARAMETERS LIKE 'DATA_RETENTION_TIME_IN_DAYS' IN DATABASE PROD;
```

### Retention limits

- Default Time Travel retention is **1 day**.
- Standard Edition supports `0` or `1` day.
- Enterprise Edition or higher supports up to **90 days** for permanent tables/databases/schemas.
- Transient tables have a maximum Time Travel retention of **1 day** and no Fail-safe.
- `DATA_RETENTION_TIME_IN_DAYS = 0` disables normal Time Travel recovery unless an applicable account minimum results in a higher effective retention period.

---

## 3. Check for a naming conflict

`UNDROP` fails if an active table with the same name already exists.

This often happens when someone recreates the table after the accidental drop.

Check:

```sql
SHOW TABLES LIKE '<table_name>' IN SCHEMA <db>.<schema>;
```

If a replacement exists, preserve it by renaming it:

```sql
ALTER TABLE <db>.<schema>.<table>
RENAME TO <table>_replacement;
```

Then recover the original:

```sql
UNDROP TABLE <db>.<schema>.<table>;
```

---

## 4. Restore the table

```sql
UNDROP TABLE PROD.FINANCE.LEDGER;
```

A table is restored into the database and schema where it existed when it was dropped.

### Multiple dropped versions with the same name

`UNDROP TABLE <name>` restores the most recently dropped version.

If multiple dropped versions exist, get their system-generated IDs from Account Usage:

```sql
SELECT
    table_id,
    table_name,
    table_schema,
    table_catalog,
    created,
    deleted
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLES
WHERE table_catalog = 'PROD'
  AND table_schema = 'FINANCE'
  AND table_name = 'LEDGER'
  AND deleted IS NOT NULL
ORDER BY deleted DESC;
```

Then restore the desired version explicitly:

```sql
UNDROP TABLE IDENTIFIER('<table_id>');
```

`ACCOUNT_USAGE.TABLES` can have latency, so use `SHOW TABLES HISTORY` as the first-line incident check and the Account Usage view when you specifically need the historical object ID.

---

## 5. Validate the recovery

Confirm that the table is active again:

```sql
SHOW TABLES LIKE 'LEDGER' IN SCHEMA PROD.FINANCE;
```

Then perform the appropriate data checks:

```sql
SELECT COUNT(*)
FROM PROD.FINANCE.LEDGER;

SELECT *
FROM PROD.FINANCE.LEDGER
LIMIT 10;
```

Also verify any dependent views, dbt models/tests, streams, tasks, or other pipelines affected by the drop.

---

## If the Time Travel window has expired

### Permanent tables

After Time Travel expires, data for permanent tables normally enters **Fail-safe** for 7 days.

Fail-safe cannot be queried or restored using `UNDROP`; recovery requires Snowflake Support and is intended for exceptional recovery scenarios.

### Transient tables

Transient tables have **no Fail-safe**. After the Time Travel retention period expires, Snowflake recovery is no longer available.

A useful storage-level diagnostic is:

```sql
SELECT
    table_catalog,
    table_schema,
    table_name,
    id,
    is_transient,
    active_bytes,
    time_travel_bytes,
    failsafe_bytes,
    table_dropped,
    table_entered_failsafe
FROM SNOWFLAKE.ACCOUNT_USAGE.TABLE_STORAGE_METRICS
WHERE table_catalog = 'PROD'
  AND table_schema = 'FINANCE'
  AND table_name = 'LEDGER';
```

`TABLE_ENTERED_FAILSAFE` being populated means the dropped permanent table is no longer recoverable with `UNDROP`.

---

## Important edge cases

### Dropped schema or database

Use the corresponding history command:

```sql
SHOW SCHEMAS HISTORY LIKE '<schema_name>' IN DATABASE <db>;
SHOW DATABASES HISTORY LIKE '<database_name>';
```

Then:

```sql
UNDROP SCHEMA <db>.<schema>;
UNDROP DATABASE <db>;
```

When an entire database is dropped, Snowflake uses the database's retention period for its child schemas/tables. Similarly, when a schema is dropped, its child tables follow the schema's retention period. Explicitly different child retention settings are not honored for recovery of a dropped container.

### Hybrid tables

Hybrid tables cannot currently be restored with `UNDROP TABLE`. Hybrid tables inside an undropped schema/database are also not restored automatically.

### Recreating the object is not recovery

```sql
CREATE TABLE PROD.FINANCE.LEDGER (...);
```

creates a new table version. It does not restore the dropped table. If the original is still in Time Travel, rename the replacement and use `UNDROP`.
