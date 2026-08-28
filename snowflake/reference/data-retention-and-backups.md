# Snowflake data retention and recovery for dbt models

## What each recovery mechanism does

Snowflake provides three layers of recovery:

| Mechanism | Use it for | Limitation |
| --- | --- | --- |
| Time Travel | Recent data manipulation language (DML) mistakes on the same table object | Limited retention window |
| Backup | Point-in-time recovery beyond a table replacement | Must be created before the incident |
| Fail-safe | Last-resort recovery of permanent tables | Snowflake Support only; not available for transient tables |

Table type limits the available recovery window:

| Table type | Maximum Time Travel | Fail-safe |
| --- | ---: | ---: |
| Permanent, Standard Edition | 1 day | 7 days |
| Permanent, Enterprise Edition or higher | 90 days | 7 days |
| Transient | 1 day | None |

An effective retention value of `0` disables self-service Time Travel.

## Why `CREATE OR REPLACE` matters

In this environment, a dbt `table` model uses regular create table as select
(CTAS):

```sql
CREATE OR REPLACE TABLE PROD_DB.CRITICAL_MODELS.FACT_TRANSACTIONS AS
SELECT ...;
```

This is not `CREATE OR REPLACE TRANSIENT TABLE`. In a permanent database and
schema, it creates a permanent table.

The retention problem is `OR REPLACE`:

| Clause | What it controls |
| --- | --- |
| `TRANSIENT` | Table type, Time Travel limit, and Fail-safe availability |
| `OR REPLACE` | Drops the old table object and creates a new object |
| `AS SELECT` | Populates the new table from a query |

```text
Before dbt run                      After dbt run
FACT_TRANSACTIONS, object 101       FACT_TRANSACTIONS, object 202
history belongs to object 101       new history starts for object 202
```

Time Travel on object `202` cannot cross into object `101`. The dropped object
can be recovered with Time Travel and `UNDROP` only while its retention remains
active. An earlier Backup or best-effort Fail-safe recovery might still exist.

## Decision tree

```text
START: critical dbt model
|
+-- First check SHOW TABLES: what is kind?
|   |
|   +-- TRANSIENT
|   |     +-- Need only 1 day and normal runs use DML?
|   |     |     +-- Set table-level Time Travel to 1 day.
|   |     +-- Need longer recovery or Schema-level Backup?
|   |           +-- Migrate it or make a permanent CTAS copy first.
|   |
|   +-- TABLE: permanent, eligible for Backup and Fail-safe;
|             Enterprise Edition or higher can exceed 1 day of Time Travel.
|
+-- Then check how dbt writes after the target exists
|   |
|   +-- Incremental DML: merge, delete+insert, or microbatch
|   |     +-- Set Time Travel on that specific table.
|   |     +-- Block accidental --full-refresh.
|   |
|   +-- Full result recomputed with incremental + insert_overwrite
|   |     +-- Protect the one-time migration first.
|   |     +-- Later runs use Time Travel.
|   |     +-- Schema-level Backup remains compatible.
|   |
|   +-- Table materialization or --full-refresh uses OR REPLACE
|         +-- Take a Schema-level Backup before the run.
|
+-- A bad run already completed?
    |
    +-- DML changed the same table object
    |     |
    |     +-- Still inside Time Travel?
    |     |     +-- Query AT or BEFORE.
    |     |     +-- Clone the historical version on the side.
    |     |     +-- Restore with INSERT OVERWRITE.
    |     |
    |     +-- Time Travel expired?
    |           +-- Restore a Backup, if one exists.
    |           +-- For a permanent table, ask Snowflake Support whether
    |               best-effort Fail-safe recovery is possible.
    |
    +-- CREATE OR REPLACE or --full-refresh created a new object
          |
          +-- Schema-level Backup exists: restore it on the side.
          +-- No Backup, but dropped object is in Time Travel: UNDROP it.
          +-- Neither is available: ask Snowflake Support about best-effort
              Fail-safe recovery for a permanent table.
```

## Confirm table type and retention

Check the effective setting on the actual model:

```sql
SHOW TABLES LIKE 'FACT_TRANSACTIONS'
    IN SCHEMA PROD_DB.CRITICAL_MODELS
    ->> SELECT
            "name",
            "kind",
            "retention_time"
        FROM $1;
```

| name | kind | retention_time |
| --- | --- | ---: |
| `FACT_TRANSACTIONS` | `TABLE` or `TRANSIENT` | `<days>` |

`TABLE` means permanent. Do not infer the type from dbt; inspect the object and
the SQL that dbt actually executed.

If a critical transient table needs more than one day of protection, take a
permanent physical copy before migrating it:

```sql
CREATE DATABASE IF NOT EXISTS BACKUP_DB;
CREATE SCHEMA IF NOT EXISTS BACKUP_DB.CRITICAL_MODELS;

CREATE TABLE BACKUP_DB.CRITICAL_MODELS.FACT_TRANSACTIONS_PRE_MIGRATION AS
SELECT *
FROM PROD_DB.CRITICAL_MODELS.FACT_TRANSACTIONS;
```

CTAS uses a warehouse and writes a full copy. Verify that the destination
database and schema are permanent.

## Incremental model: Time Travel

Use this route when normal dbt runs update the existing table with DML.

### Set retention on the specific table

```sql
ALTER TABLE PROD_DB.CRITICAL_MODELS.FACT_TRANSACTIONS
    SET DATA_RETENTION_TIME_IN_DAYS = 7;
```

More than one day requires a permanent table on Enterprise Edition or higher.
A transient table accepts only `0` or `1`.

Protect an incremental model from an accidental command-line full refresh:

```jinja
{{ config(
    materialized='incremental',
    full_refresh=false
) }}
```

### View historical data

Use a timestamp when the incident time is known:

```sql
SELECT
    TRANSACTION_ID,
    TRANSACTION_DATE,
    AMOUNT
FROM PROD_DB.CRITICAL_MODELS.FACT_TRANSACTIONS
AT (TIMESTAMP => '2026-08-19 10:00:00 -05:00'::TIMESTAMP_TZ)
ORDER BY TRANSACTION_ID
LIMIT 100;
```

Use the bad DML statement's query ID to target the state immediately before the
statement completed:

```sql
SELECT
    TRANSACTION_ID,
    TRANSACTION_DATE,
    AMOUNT
FROM PROD_DB.CRITICAL_MODELS.FACT_TRANSACTIONS
BEFORE (STATEMENT => '<bad_query_id>')
ORDER BY TRANSACTION_ID
LIMIT 100;
```

Either query returns the historical row shape:

| TRANSACTION_ID | TRANSACTION_DATE | AMOUNT |
| --- | --- | ---: |
| `<id>` | `<date>` | `<amount>` |

`AT` includes the specified point. `STATEMENT` accepts query IDs from the last
14 days. For older incidents still inside Time Travel, use a timestamp.
Concurrent changes committed while the bad statement ran can appear in its
`BEFORE` result.

### Clone the historical version on the side

Yes, a historical table can be cloned without changing production:

```sql
CREATE DATABASE IF NOT EXISTS RECOVERY_DB;
CREATE SCHEMA IF NOT EXISTS RECOVERY_DB.CRITICAL_MODELS;

-- Permanent source
CREATE TABLE RECOVERY_DB.CRITICAL_MODELS.FACT_TRANSACTIONS_BEFORE_REFRESH
    CLONE PROD_DB.CRITICAL_MODELS.FACT_TRANSACTIONS
    BEFORE (STATEMENT => '<bad_query_id>')
    COPY GRANTS;

-- Transient source
CREATE TRANSIENT TABLE RECOVERY_DB.CRITICAL_MODELS.FACT_TRANSACTIONS_TRANSIENT_RECOVERY
    CLONE PROD_DB.CRITICAL_MODELS.FACT_TRANSACTIONS
    BEFORE (STATEMENT => '<bad_query_id>')
    COPY GRANTS;
```

The clone is initially zero-copy. It must be created while the historical state
is still inside Time Travel and the current table object existed at that point.
After `CREATE OR REPLACE`, use a Schema-level Backup or `UNDROP` instead. Run
only the clone variant that matches the source type.

Validate it:

```sql
SELECT COUNT(*) AS ROW_COUNT
FROM RECOVERY_DB.CRITICAL_MODELS.FACT_TRANSACTIONS_BEFORE_REFRESH;
```

| ROW_COUNT |
| ---: |
| `<expected rows>` |

Restore the data while preserving the production table object:

```sql
INSERT OVERWRITE INTO PROD_DB.CRITICAL_MODELS.FACT_TRANSACTIONS
    (TRANSACTION_ID, TRANSACTION_DATE, AMOUNT)
SELECT
    TRANSACTION_ID,
    TRANSACTION_DATE,
    AMOUNT
FROM RECOVERY_DB.CRITICAL_MODELS.FACT_TRANSACTIONS_BEFORE_REFRESH;
```

Use the complete explicit column list. `INSERT OVERWRITE` is transactional and
preserves the table object and grants. Recovery requires `INSERT` and `DELETE`
on the target plus `SELECT` on the recovery table.

## Full recomputation: `insert_overwrite`

`INSERT OVERWRITE` = `TRUNCATE` + `INSERT`, so the table never goes through `DROP` + `CTAS` phase.
`insert_overwrite` works with both Time Travel and Schema-level Backup on
dbt-snowflake `1.9.2` or newer. After the target exists, a normal run uses DML
and preserves the table object. The first run and a permitted full refresh do
not follow that path.

Use an incremental materialization even though the query returns the complete
table:

```jinja
{{ config(
    materialized='incremental',
    incremental_strategy='insert_overwrite',
    full_refresh=false
) }}

select
    transaction_id,
    transaction_date,
    amount
from {{ ref('stg_transactions') }}
```

The example omits `transient` because this environment already emits regular
CTAS for these models. If `SHOW TABLES` reports `TRANSIENT` elsewhere, migrate
that target before relying on retention beyond one day or schema Backup.

Do not add an `is_incremental()` filter. Snowflake's strategy overwrites the
entire target, and `unique_key` is ignored.

| Question | Answer |
| --- | --- |
| Does it preserve the table object? | Yes, on normal runs after the table exists |
| Does Time Travel retain the prior state? | Yes, within the configured retention period |
| Does it work with a Schema-level Backup? | Yes, for an eligible permanent target; Backup captures its own point-in-time state independently |
| Is it guaranteed for every dbt run? | No; the first run creates the table, and a table materialization or permitted `--full-refresh` uses replacement DDL |

Test one run outside production and confirm that the executed statement is
`INSERT OVERWRITE`, not `CREATE OR REPLACE TABLE`. Full-table rewrites can
retain approximately another full table generation during Time Travel, so
monitor storage.

## Schema-level Backup

Use this route when dbt can replace tables with `CREATE OR REPLACE`, including
table materializations and full refreshes.

A table-level backup set follows one table's internal identifier. After
replacement, it remains attached to the dropped object. A schema-level set
follows the schema and continues protecting eligible replacement tables.

### Create the policy and Backup set

Keep both objects outside the schema managed by dbt:

```sql
CREATE DATABASE IF NOT EXISTS BACKUP_ADMIN;
CREATE SCHEMA IF NOT EXISTS BACKUP_ADMIN.CONTROL;

CREATE BACKUP POLICY BACKUP_ADMIN.CONTROL.CRITICAL_DAILY
    SCHEDULE = '1440 MINUTE'
    EXPIRE_AFTER_DAYS = 30;

CREATE BACKUP SET BACKUP_ADMIN.CONTROL.CRITICAL_MODELS
    FOR SCHEMA PROD_DB.CRITICAL_MODELS
    WITH BACKUP POLICY BACKUP_ADMIN.CONTROL.CRITICAL_DAILY;
```

Scheduled backups can occur in the middle of a dbt run. Add a manual checkpoint
immediately before a destructive build:

```sql
ALTER BACKUP SET BACKUP_ADMIN.CONTROL.CRITICAL_MODELS
    ADD BACKUP;

SHOW BACKUPS IN BACKUP SET BACKUP_ADMIN.CONTROL.CRITICAL_MODELS
    ->> SELECT
            "created_on",
            "backup_id",
            "expire_on"
        FROM $1
        ORDER BY "created_on" DESC;
```

| created_on | backup_id | expire_on |
| --- | --- | --- |
| `<checkpoint timestamp>` | `<backup identifier>` | `<expiration timestamp>` |

Do not start the dbt run until the checkpoint appears. New schema and database
Backups exclude transient tables when Snowflake's `2026_06` behavior change is
active, so verify that critical models are permanent.

### Restore the Backup on the side

A Backup cannot be queried directly. Restore it under a new schema name:

```sql
CREATE DATABASE IF NOT EXISTS RESTORE_DB;

CREATE SCHEMA RESTORE_DB.CRITICAL_MODELS_20260819
    FROM BACKUP SET BACKUP_ADMIN.CONTROL.CRITICAL_MODELS
    IDENTIFIER '<backup_id>';
```

Inspect the restored table:

```sql
SELECT COUNT(*) AS ROW_COUNT
FROM RESTORE_DB.CRITICAL_MODELS_20260819.FACT_TRANSACTIONS;
```

| ROW_COUNT |
| ---: |
| `<expected rows>` |

Recover only the required model while preserving the production table object:

```sql
INSERT OVERWRITE INTO PROD_DB.CRITICAL_MODELS.FACT_TRANSACTIONS
    (TRANSACTION_ID, TRANSACTION_DATE, AMOUNT)
SELECT
    TRANSACTION_ID,
    TRANSACTION_DATE,
    AMOUNT
FROM RESTORE_DB.CRITICAL_MODELS_20260819.FACT_TRANSACTIONS;
```

The restored schema is independent. Further backups in the original Backup set
continue to follow `PROD_DB.CRITICAL_MODELS`.

## Recover after `CREATE OR REPLACE` without a Backup

Check whether the dropped table object is still in Time Travel:

```sql
SHOW TABLES HISTORY LIKE 'FACT_TRANSACTIONS'
    IN SCHEMA PROD_DB.CRITICAL_MODELS;
```

| name | kind | retention_time | created_on | dropped_on |
| --- | --- | ---: | --- | --- |
| `FACT_TRANSACTIONS` | `TABLE` or `TRANSIENT` | `<days>` | `<new object timestamp>` | `NULL` |
| `FACT_TRANSACTIONS` | `TABLE` or `TRANSIENT` | `<days>` | `<old object timestamp>` | `<replacement timestamp>` |

Move the new object aside, then restore the most recently dropped object:

```sql
ALTER TABLE PROD_DB.CRITICAL_MODELS.FACT_TRANSACTIONS
    RENAME TO FACT_TRANSACTIONS_BAD_20260819;

UNDROP TABLE PROD_DB.CRITICAL_MODELS.FACT_TRANSACTIONS;
```

Run this during a maintenance window because the production name changes
between statements. If retention has expired, Snowflake Support might be able
to recover a permanent table during Fail-safe, but recovery is best-effort and
not guaranteed. A transient table has no Fail-safe.

## Other options

| Option | Best use | Main limitation |
| --- | --- | --- |
| Current-state zero-copy clone | Fast checkpoint before one deployment | Mutable; requires cleanup and retention management |
| Permanent CTAS copy | Protect a transient table or change its lifecycle | Warehouse compute and full-copy storage |
| External Parquet unload | Account-independent archive | Data only; restore schema and policies separately |
| dbt snapshot | Row-level slowly changing dimension history | Not a complete table backup |
| Replication or failover | Region or account disaster recovery | Bad source changes can replicate |
