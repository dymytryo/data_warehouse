# Snowflake object copy and removal runbook

This runbook controls how a legacy Snowflake object is copied, repointed, or
removed during an acquisition data integration. Each action produces reviewable
evidence and preserves a rollback path before the source object is retired.

## 1. Classify the object

Record the object owner, type, refresh status, downstream consumers, financial
reporting impact, and destination. Choose one disposition:

1. Copy historical data once into Iceberg.
2. Rebuild active transformation logic in dbt.
3. Keep a temporary compatibility view.
4. Remove an unused or irreparably broken object.

The migration tracker must contain the owner and disposition before execution.

## 2. Check dependencies

Search version-controlled SQL, scheduled jobs, BI workbooks, and application
configuration for the fully qualified source name. Confirm the result with the
owner. For financial reporting objects, retain the approval as SOX evidence.

## 3. Copy a historical table

Validate the most recent source timestamp, then create the target copy.

~~~sql
SELECT MAX(<updated_column>) AS latest_source_timestamp
FROM <source_catalog>.<source_schema>.<source_table>;

CREATE TABLE <target_catalog>.<target_schema>.<target_table> AS
SELECT *
FROM <source_catalog>.<source_schema>.<source_table>;
~~~

Reconcile at least row count, date boundaries, and the agreed business key.
High-risk financial tables also require aggregate comparisons for relevant
amount columns.

~~~sql
SELECT
    COUNT(*) AS row_count,
    COUNT(DISTINCT <business_key>) AS distinct_keys,
    MIN(<updated_column>) AS first_timestamp,
    MAX(<updated_column>) AS last_timestamp
FROM <catalog>.<schema>.<table>;
~~~

Save the copy statement, validation output, reviewer, and execution timestamp in
the migration audit folder.

## 4. Preserve required view logic

Capture the source data definition language (DDL), convert the logic to the
target SQL dialect, and implement it as a dbt model or compatibility view.

~~~sql
SELECT GET_DDL(
    'VIEW',
    '<source_catalog>.<source_schema>.<source_view>'
);
~~~

Validate availability, column shape, row composition, and business totals before
repointing any consumer.

## 5. Remove an unused or broken object

Document the dependency search and the reason for removal. Store the approved
drop statement before execution.

~~~sql
DROP VIEW IF EXISTS <source_catalog>.<source_schema>.<source_view>;
DROP TABLE IF EXISTS <source_catalog>.<source_schema>.<source_table>;
~~~

Do not infer that a failing query means an object is unused. A broken object
still requires an owner and dependency review.

## 6. Repoint and observe

1. Repoint downstream connections to the target.
2. Run the parity suite and attach the evidence.
3. Observe the target through the agreed rollback window.
4. Confirm that scheduled jobs and BI refreshes succeed.
5. Obtain owner approval before retiring the source.

## 7. Roll back when a gate fails

Restore the prior connection, keep the source object available, and mark the
tracker as blocked. Record the failed check and remediation owner. Repeat the
full validation sequence after the fix rather than approving only the failed
query.

## Required evidence

| Evidence | Purpose |
| --- | --- |
| Owner and disposition | Establish accountability |
| Dependency-search result | Prevent an unplanned consumer outage |
| Copy or replacement SQL | Make the change reproducible |
| Row, shape, and composition checks | Demonstrate data parity |
| Consumer refresh result | Confirm end-to-end operation |
| Approval and timestamp | Support the SOX audit trail |
| Rollback end time | Prevent premature source removal |
