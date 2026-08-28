# Snowflake secure data sharing

## What is a share?

A Snowflake share is a named account-level object that records which database
objects are available to which consumer accounts. The share stores grants and
account targets, not rows. No data is copied when a consumer imports it.

The provider owns and updates the source objects. The consumer creates one
read-only database from the share, grants access to local roles, and uses a
warehouse in the consumer account to run queries.

Secure Data Sharing is the overall feature. A secure view is an object placed in
a share when the provider must restrict columns or rows and conceal the view
definition.

## How access works

The imported database is a metadata and access layer. A consumer query follows
that metadata back to the provider's secure view or table and reads the
provider's underlying micro-partitions. There is no extraction, transfer, or
second stored copy.

```text
Provider account

SOURCE_DB_1 table --------+
                           +--> secure view in SHARING_DB
SOURCE_DB_2 table --------+              |
                                         v
                                       SHARE
                                         |
                              add consumer account
                                         |
                                         v
Consumer account

inbound share --> read-only imported database --> local role
                                                    |
                                             consumer warehouse
                                                    |
                                                  query
```

| Cost or change | Provider account | Consumer account |
| --- | --- | --- |
| Data storage | Stores the source micro-partitions and pays their storage cost | No duplicate storage for the imported database |
| Query compute | No warehouse is used merely to create the share | Uses and pays for its own warehouse when querying |
| Source update | Writes new source micro-partitions | Sees the updated result through the share without a copy or refresh job |

1. The provider creates the table or secure view to expose.
2. The provider creates a share and grants `USAGE` on the sharing database and
   schema, plus `SELECT` on the shared object.
3. The provider adds the consumer account to the share.
4. The consumer sees an `INBOUND` share and creates one read-only database from
   it.
5. The consumer grants `IMPORTED PRIVILEGES` on that database to a local role.
6. The local role queries the imported object through a consumer warehouse.
   Provider changes become visible without a copy or refresh job.

## Object and privilege flow

| Provider object or action | Share privilege or action | Consumer result |
| --- | --- | --- |
| Sharing database | `USAGE` | Becomes the imported database namespace |
| Shared schema | `USAGE` | Schema is visible in the imported database |
| Additional source database | `REFERENCE_USAGE` | Secure-view dependency resolves; source database stays hidden |
| Secure view | `SELECT` | View is queryable |
| Consumer account | `ALTER SHARE ... ADD ACCOUNTS` | Share appears as `INBOUND` |

The imported database is read-only. The consumer cannot browse source databases
that have only `REFERENCE_USAGE`.

## Rules before setup

- Use roles and object grants, not a share, when the provider and consumer use
  the same Snowflake account.
- Direct shares target accounts in the same Snowflake region. For cross-region
  access, use a listing with auto-fulfillment or follow the
  [replication-group guide](replication-groups-for-secure-data-sharing.md) to
  replicate the share and every dependent database.
- A share can have `USAGE` on only one database.
- A cross-database secure view requires `REFERENCE_USAGE` on every additional
  referenced database before `SELECT` is granted on the view.
- Every referenced database must belong to the provider account.
- Cross-database sharing must use direct grants to the share. Snowflake database
  roles cannot receive `REFERENCE_USAGE`.

## Example: Finance shares workforce-budget data with People Analytics

| Item | Name |
| --- | --- |
| Provider account | `YOUR_ORG.FINANCE_PROD` |
| Consumer account | `YOUR_ORG.PEOPLE_ANALYTICS` |
| Budget source | `FINANCE_DB.MARTS.WORKFORCE_BUDGET` |
| Department source | `PEOPLE_DB.CURATED.DEPARTMENT_DIRECTORY` |
| Sharing database | `FINANCE_SHARE_DB` |
| Shared secure view | `FINANCE_SHARE_DB.PEOPLE_ANALYTICS.WORKFORCE_BUDGET_V` |
| Share | `FINANCE_TO_PEOPLE_SHARE` |
| Imported database | `FINANCE_SHARED_DB` |
| Consumer role | `PEOPLE_ANALYST` |
| Consumer warehouse | `PEOPLE_ANALYTICS_WH` |

### 1. Get the consumer account identifier

Run in the People Analytics account:

```sql
SELECT
    CURRENT_ORGANIZATION_NAME() AS ORGANIZATION_NAME,
    CURRENT_ACCOUNT_NAME() AS ACCOUNT_NAME,
    CURRENT_REGION() AS SNOWFLAKE_REGION;
```

Example result:

| ORGANIZATION_NAME | ACCOUNT_NAME | SNOWFLAKE_REGION |
| --- | --- | --- |
| `YOUR_ORG` | `PEOPLE_ANALYTICS` | `AWS_US_WEST_2` |

Use the organization and account values as the consumer identifier
`YOUR_ORG.PEOPLE_ANALYTICS`. Run the same query in the provider account to
confirm that both accounts are in the same region before using a direct share.

### 2. Create the sharing database and secure view

Run in the Finance account:

```sql
USE ROLE ACCOUNTADMIN;

CREATE DATABASE FINANCE_SHARE_DB
    COMMENT = 'Curated objects shared by Finance';

CREATE SCHEMA FINANCE_SHARE_DB.PEOPLE_ANALYTICS;
```

The share will use `FINANCE_SHARE_DB` as its single database. The source tables
remain in `FINANCE_DB` and `PEOPLE_DB`.

```sql
CREATE SECURE VIEW
    FINANCE_SHARE_DB.PEOPLE_ANALYTICS.WORKFORCE_BUDGET_V AS
SELECT
    B.FISCAL_MONTH,
    D.DEPARTMENT_NAME AS DEPARTMENT,
    B.BUDGETED_HEADCOUNT,
    B.BUDGETED_COMPENSATION
FROM FINANCE_DB.MARTS.WORKFORCE_BUDGET AS B
INNER JOIN PEOPLE_DB.CURATED.DEPARTMENT_DIRECTORY AS D
    ON B.DEPARTMENT_ID = D.DEPARTMENT_ID;
```

The view exposes approved department-level budget rows. It does not expose
employee-level fields or either base table.

### 3. Validate the secure view

Run in the Finance account before granting the view to the share:

```sql
SELECT
    FISCAL_MONTH,
    DEPARTMENT,
    BUDGETED_HEADCOUNT,
    BUDGETED_COMPENSATION
FROM FINANCE_SHARE_DB.PEOPLE_ANALYTICS.WORKFORCE_BUDGET_V
ORDER BY FISCAL_MONTH, DEPARTMENT
LIMIT 3;
```

Example result:

| FISCAL_MONTH | DEPARTMENT | BUDGETED_HEADCOUNT | BUDGETED_COMPENSATION |
| --- | --- | ---: | ---: |
| `2026-07-01` | Engineering | 125 | 18,750,000 |
| `2026-07-01` | Finance | 32 | 4,160,000 |
| `2026-07-01` | People | 28 | 3,360,000 |

### 4. Create the share and grant provider access

Run in the Finance account:

```sql
CREATE SHARE FINANCE_TO_PEOPLE_SHARE
    COMMENT = 'Workforce budget data for People Analytics';
```

`ACCOUNTADMIN` can create shares by default. A custom administration role can
be used instead if it has the global `CREATE SHARE` privilege and the required
privileges on the shared objects.

Grant privileges in dependency order:

```sql
GRANT USAGE ON DATABASE FINANCE_SHARE_DB
    TO SHARE FINANCE_TO_PEOPLE_SHARE;

GRANT USAGE ON SCHEMA FINANCE_SHARE_DB.PEOPLE_ANALYTICS
    TO SHARE FINANCE_TO_PEOPLE_SHARE;

GRANT REFERENCE_USAGE ON DATABASE FINANCE_DB
    TO SHARE FINANCE_TO_PEOPLE_SHARE;

GRANT REFERENCE_USAGE ON DATABASE PEOPLE_DB
    TO SHARE FINANCE_TO_PEOPLE_SHARE;

GRANT SELECT ON VIEW
    FINANCE_SHARE_DB.PEOPLE_ANALYTICS.WORKFORCE_BUDGET_V
    TO SHARE FINANCE_TO_PEOPLE_SHARE;
```

The `USAGE` grants expose the sharing database and schema. `REFERENCE_USAGE`
allows the secure view to resolve objects in `FINANCE_DB` and `PEOPLE_DB`
without exposing those databases to the consumer.

### 5. Verify the provider grants

Run in the Finance account:

```sql
SHOW GRANTS TO SHARE FINANCE_TO_PEOPLE_SHARE;
```

Relevant output columns:

| PRIVILEGE | GRANTED_ON | NAME |
| --- | --- | --- |
| `USAGE` | `DATABASE` | `FINANCE_SHARE_DB` |
| `USAGE` | `SCHEMA` | `FINANCE_SHARE_DB.PEOPLE_ANALYTICS` |
| `REFERENCE_USAGE` | `DATABASE` | `FINANCE_DB` |
| `REFERENCE_USAGE` | `DATABASE` | `PEOPLE_DB` |
| `SELECT` | `TABLE` | `FINANCE_SHARE_DB.PEOPLE_ANALYTICS.WORKFORCE_BUDGET_V` |

`SHOW GRANTS TO SHARE` reports a shared secure view as `TABLE`. `DESC SHARE`,
used below, identifies it as `VIEW`.

### 6. Add the consumer and verify the outbound share

Run in the Finance account:

```sql
ALTER SHARE FINANCE_TO_PEOPLE_SHARE
    ADD ACCOUNTS = YOUR_ORG.PEOPLE_ANALYTICS;
```

Granting `USAGE` on the sharing database must happen before this command.

```sql
SHOW SHARES LIKE 'FINANCE_TO_PEOPLE_SHARE';
```

Relevant output columns in the Finance account:

| KIND | OWNER_ACCOUNT | NAME | DATABASE_NAME | TO |
| --- | --- | --- | --- | --- |
| `OUTBOUND` | `YOUR_ORG.FINANCE_PROD` | `FINANCE_TO_PEOPLE_SHARE` | `FINANCE_SHARE_DB` | `YOUR_ORG.PEOPLE_ANALYTICS` |

The Finance account should show `OUTBOUND` in `KIND` and the People Analytics
account in `TO`.

### 7. Inspect the inbound share

Run in the People Analytics account:

```sql
USE ROLE ACCOUNTADMIN;

SHOW SHARES LIKE 'FINANCE_TO_PEOPLE_SHARE';
```

Relevant output columns in the People Analytics account:

| KIND | OWNER_ACCOUNT | NAME | DATABASE_NAME | TO |
| --- | --- | --- | --- | --- |
| `INBOUND` | `YOUR_ORG.FINANCE_PROD` | `FINANCE_TO_PEOPLE_SHARE` |  |  |

`INBOUND` means the share is available to import. The empty `DATABASE_NAME`
means this account has not created a database from it yet.

```sql
DESC SHARE YOUR_ORG.FINANCE_PROD.FINANCE_TO_PEOPLE_SHARE;
```

Expected result before import:

| KIND | NAME |
| --- | --- |
| `DATABASE` | `<DB>` |
| `SCHEMA` | `<DB>.PEOPLE_ANALYTICS` |
| `VIEW` | `<DB>.PEOPLE_ANALYTICS.WORKFORCE_BUDGET_V` |

`FINANCE_DB` and `PEOPLE_DB` do not appear. They are dependencies of the secure
view, not shared objects. `<DB>` is replaced by the local database name after
the share is imported.

### 8. Create the imported database

Run in the People Analytics account:

```sql
CREATE DATABASE FINANCE_SHARED_DB
    FROM SHARE YOUR_ORG.FINANCE_PROD.FINANCE_TO_PEOPLE_SHARE;

SHOW DATABASES LIKE 'FINANCE_SHARED_DB';
```

Relevant verification columns:

| NAME | ORIGIN | OWNER |
| --- | --- | --- |
| `FINANCE_SHARED_DB` | `YOUR_ORG.FINANCE_PROD.FINANCE_TO_PEOPLE_SHARE` | `ACCOUNTADMIN` |

The imported database is read-only. Finance continues to own the source data;
updates made by Finance become visible through the view without a copy or
refresh job.

### 9. Grant consumer access

Run in the People Analytics account. Replace `<PEOPLE_ANALYST_USER>` with the
user who will run the query:

```sql
CREATE ROLE IF NOT EXISTS PEOPLE_ANALYST;

CREATE WAREHOUSE IF NOT EXISTS PEOPLE_ANALYTICS_WH
    WAREHOUSE_SIZE = XSMALL
    AUTO_SUSPEND = 60
    INITIALLY_SUSPENDED = TRUE;

GRANT IMPORTED PRIVILEGES ON DATABASE FINANCE_SHARED_DB
    TO ROLE PEOPLE_ANALYST;

GRANT USAGE ON WAREHOUSE PEOPLE_ANALYTICS_WH
    TO ROLE PEOPLE_ANALYST;

GRANT ROLE PEOPLE_ANALYST TO USER <PEOPLE_ANALYST_USER>;
```

`IMPORTED PRIVILEGES` is the consumer-side match for the direct grants used by
the provider. Warehouse `USAGE` lets the role run queries; the People Analytics
account is billed for that compute.

### 10. Query the shared view

Run in the People Analytics account as the user granted `PEOPLE_ANALYST`:

```sql
USE ROLE PEOPLE_ANALYST;
USE WAREHOUSE PEOPLE_ANALYTICS_WH;

SELECT
    FISCAL_MONTH,
    DEPARTMENT,
    BUDGETED_HEADCOUNT,
    BUDGETED_COMPENSATION
FROM FINANCE_SHARED_DB.PEOPLE_ANALYTICS.WORKFORCE_BUDGET_V
ORDER BY FISCAL_MONTH, DEPARTMENT;
```

Example result:

| FISCAL_MONTH | DEPARTMENT | BUDGETED_HEADCOUNT | BUDGETED_COMPENSATION |
| --- | --- | ---: | ---: |
| `2026-07-01` | Engineering | 125 | 18,750,000 |
| `2026-07-01` | Finance | 32 | 4,160,000 |
| `2026-07-01` | People | 28 | 3,360,000 |

## Maintain the shared view

Replacing a view normally creates a new object and can remove its explicit
share grant. Use `COPY GRANTS` when changing the view definition:

```sql
CREATE OR REPLACE SECURE VIEW
    FINANCE_SHARE_DB.PEOPLE_ANALYTICS.WORKFORCE_BUDGET_V
    COPY GRANTS AS
SELECT
    B.FISCAL_MONTH,
    D.DEPARTMENT_NAME AS DEPARTMENT,
    B.BUDGETED_HEADCOUNT,
    B.BUDGETED_COMPENSATION
FROM FINANCE_DB.MARTS.WORKFORCE_BUDGET AS B
INNER JOIN PEOPLE_DB.CURATED.DEPARTMENT_DIRECTORY AS D
    ON B.DEPARTMENT_ID = D.DEPARTMENT_ID;
```

Grant each new shared view explicitly. Future grants to objects in a share are
not supported.
