# Snowflake table and view types

A Snowflake table owns or references data. A view is a named query over other
objects. The object type affects persistence, recovery, query performance,
security, and cost.

This note follows the core objects covered in Chapter 6 of *Snowflake SnowPro
Advanced Architect Certification Companion*. Specialized objects such as
dynamic tables, Iceberg tables, [hybrid tables](hybrid-tables.md), event tables,
and semantic views are separate topics.

```text
Core objects covered in this note
|
+-- Tables
|   +-- Snowflake-managed: permanent, transient, temporary
|   +-- Externally stored: external
|
+-- Views
    +-- Evaluation: non-materialized or materialized
    +-- Security: standard or secure
```

## Table types

Permanent, transient, and temporary tables use Snowflake-managed storage. Their
main difference is persistence and recovery protection. An external table
stores metadata in Snowflake while its files remain in cloud storage.

| Type | Lifetime | Time Travel | Fail-safe | Practical use |
| --- | --- | --- | --- | --- |
| Permanent | Until explicitly dropped | 0 or 1 day on Standard Edition; up to 90 days on Enterprise Edition or higher | 7 days | Critical and long-lived data |
| Transient | Until explicitly dropped | 0 or 1 day | None | Reproducible intermediate data |
| Temporary | Remainder of the creating session | 0 or 1 day, limited by the session lifetime | None | Session-specific scratch work |
| External | Metadata remains until explicitly dropped; file lifetime is controlled in cloud storage | Not supported | None | Querying files without loading them into native tables |

A permanent table is the default when neither `TRANSIENT` nor `TEMPORARY`
appears in the statement and its database and schema are permanent. Every table
inside a transient database or schema is transient. Transient and temporary
tables have no Fail-safe, and a table cannot be converted between permanent and
transient in place.

```sql
CREATE TABLE FINANCE.FACT_TRANSACTIONS (
    TRANSACTION_ID NUMBER,
    TRANSACTION_DATE DATE,
    AMOUNT NUMBER(18, 2)
);

CREATE TRANSIENT TABLE WORK.INT_TRANSACTION_ENRICHMENT AS
SELECT ...;

CREATE TEMPORARY TABLE SESSION_DUPLICATES AS
SELECT ...;
```

A temporary table is visible only in its creating session. If it has the same
name as a permanent or transient table, it takes precedence in that session.

An external table is read-only and does not support Time Travel. Snowflake
stores file metadata, while the source files stay in the Amazon S3, Azure
Storage, or Google Cloud Storage location referenced by an external stage. See
[External tables](external-tables.md) for the setup flow.

## `CREATE OR REPLACE` is not a table type

Create table as select (CTAS) builds a table from a query. `OR REPLACE` controls
the lifecycle of an existing object, while `TRANSIENT` controls its table type.

```sql
CREATE OR REPLACE TABLE FINANCE.FACT_TRANSACTIONS AS
SELECT ...;
```

This is a regular CTAS statement, not a transient-table statement. In a
permanent database and schema, it creates a permanent table. However,
`OR REPLACE` atomically drops the previous object and creates a new object with
a new internal identifier.

```text
Before replacement                  After replacement
FACT_TRANSACTIONS, object 101       FACT_TRANSACTIONS, object 202
history belongs to object 101       new history starts for object 202
              |
              +-- object 101 is recoverable only during its own retention
```

The replacement boundary, not CTAS itself, breaks continuity with the current
table's Time Travel history. See [Data retention and backups for dbt models](data-retention-and-backups.md)
for recovery options.

## View types

A non-materialized view stores only its query definition. A materialized view
also stores precomputed results. `SECURE` is a separate property that can be
applied to either kind, not a third, mutually exclusive storage type.

| Evaluation | Security | What Snowflake stores | Main tradeoff |
| --- | --- | --- | --- |
| Non-materialized | Standard | Query definition | No maintenance storage, but the definition is expanded and optimized as part of each referencing query |
| Non-materialized | Secure | Protected query definition | Better privacy and sharing controls, with fewer optimizer transformations |
| Materialized | Standard | Definition and precomputed results | Faster repeated access, with storage and automatic maintenance cost |
| Materialized | Secure | Protected definition and precomputed results | Combines materialization and privacy, with both cost and optimization tradeoffs |

Materialized views require Enterprise Edition and have more SQL restrictions
than regular views. Use one only when a repeated, expensive query benefits
enough to justify its storage and Snowflake-managed maintenance compute.

```sql
CREATE VIEW FINANCE.V_TRANSACTION_SUMMARY AS
SELECT TRANSACTION_DATE, SUM(AMOUNT) AS TOTAL_AMOUNT
FROM FINANCE.FACT_TRANSACTIONS
GROUP BY TRANSACTION_DATE;

CREATE MATERIALIZED VIEW FINANCE.MV_HIGH_VALUE_TRANSACTIONS AS
SELECT TRANSACTION_DATE, AMOUNT
FROM FINANCE.FACT_TRANSACTIONS
WHERE AMOUNT >= 10000;

CREATE SECURE VIEW SHARED.V_TRANSACTION_TOTALS AS
SELECT TRANSACTION_DATE, SUM(AMOUNT) AS TOTAL_AMOUNT
FROM FINANCE.FACT_TRANSACTIONS
GROUP BY TRANSACTION_DATE;
```

A secure view hides its definition from unauthorized users and restricts
optimizer behavior that could expose underlying data. This can reduce query
performance. Consumers can receive `SELECT` on the view without receiving
`SELECT` on its base tables. A materialized view can also be declared `SECURE`.
