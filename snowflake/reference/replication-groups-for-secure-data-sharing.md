# Snowflake replication groups for secure data sharing

## What replication does

Snowflake replication copies selected objects from a primary replication group
in one account to a read-only secondary replication group in another account in
the same Snowflake organization.

A Snowflake account belongs to one region. Replication does not move the same
account to another region. It sends objects to a different target account, and
that account can be in the same region, another region, or another cloud.

| Access requirement | Use |
| --- | --- |
| Users are in the same account | Role and object grants; no share or replication |
| Provider and consumer accounts are in the same region | Direct secure data share; no replication |
| A target account in the same organization needs a physical copy | Replication group; the target can be in the same or a different region |
| A consumer outside the provider organization is in another region | Replicate the databases and share to a provider account in the consumer's region, then share locally; a listing is another option |

Replication is not zero-copy. Snowflake creates a physical copy of each selected
database in the target account. If that target account then shares the replica
with local consumers, the local direct share is zero-copy. One regional replica
can therefore serve multiple local consumers without another copy per consumer.

## How the data moves

```text
Same Snowflake organization

SOURCE_ACCOUNT                            TARGET_ACCOUNT
region A                                  region A, B, or another cloud

primary replication group                secondary replication group
primary databases                         read-only secondary databases
[MP-1] [MP-2] ---- physical refresh ----> [MP-1T] [MP-2T]
primary share                             replicated share
                                                   |
                                                   | optional local share
                                                   | no additional copy
                                                   v
                                          CONSUMER_ACCOUNT
                                          same region as TARGET_ACCOUNT
                                          imported read-only database
                                                   |
                                                   +--> [MP-1T] [MP-2T]
```

`MP-1T` and `MP-2T` represent physical copies stored in the target account. If a
local consumer imports the replicated share, its database points to the target
micro-partitions and does not store another copy.

If `TARGET_ACCOUNT` is itself the intended consumer and belongs to the source
organization, grant its local roles access to the read-only secondary database
and stop there. The optional share is needed when the target account must serve
another consumer account in its region.

## Storage, compute, and freshness

| State | Physical data | Data visible in the target or consumer | Cost effect |
| --- | --- | --- | --- |
| Before replication | Source micro-partitions exist only in the source account | The target has no secondary copy | Source storage only |
| Initial refresh | Snowflake copies the selected databases into the target account | The secondary databases become available after the refresh completes | Target account pays replication compute and replica storage; cross-region or cross-cloud transfers can add data-transfer charges |
| Source changes | New or replaced micro-partitions exist in the source account | The target still sees the last completed refresh | Normal source write and storage costs; no transfer until the next refresh |
| Next refresh | Snowflake transfers the changed data and metadata | The target sees the new state after the refresh completes | Target account pays for the refresh; cross-region or cross-cloud transfer charges apply when applicable |
| Target or consumer query | A query reads the secondary database or a local imported database | The latest completed refresh is visible | The querying account pays for its warehouse; no additional data copy is created |

Replication is asynchronous. The schedule controls how often Snowflake attempts
a refresh. Consumers see the last successful refresh; actual lag can exceed the
interval when a refresh runs long or fails. A replication group creates
read-only secondary databases; it is not a failover group and cannot promote
them to writable primaries.

Refreshes use Snowflake-managed replication compute, not a user warehouse. The
target account is billed for that compute.

## Replication groups and standalone database replication

Snowflake supports group-based replication and an older, limited standalone
database-replication workflow. Use a replication group when databases and shares
must move together.

| Question | Replication group | Standalone database replication |
| --- | --- | --- |
| Replication unit | A named group refreshed as one unit | One database lineage |
| Objects | Multiple databases and shares; higher editions support additional account objects | One database |
| Configuration | `CREATE REPLICATION GROUP` with `ALLOWED_DATABASES`, `ALLOWED_SHARES`, and `ALLOWED_ACCOUNTS` | `ALTER DATABASE ... ENABLE REPLICATION TO ACCOUNTS` |
| Target object | Secondary replication group containing read-only secondary databases and replicated shares | Read-only secondary database |
| Main inventory command | `SHOW REPLICATION GROUPS` | `SHOW REPLICATION DATABASES` |
| Membership command | `SHOW DATABASES IN REPLICATION GROUP` and `SHOW SHARES IN REPLICATION GROUP` | Not applicable |

`SHOW REPLICATION DATABASES` is database-centric. It reports primary and
secondary database relationships, their accounts and regions, and the primary
database for each secondary. It does not show replication-group membership,
share membership, or refresh status.

`SHOW REPLICATION GROUPS` is container-centric. It reports each visible primary
or secondary replication or failover group, its location, object types, target
accounts, and schedule. It does not list the member databases or prove that the
last refresh succeeded.

## Objects that must be replicated

The secure view in the [secure data sharing guide](secure-data-sharing.md)
depends on objects in three databases. The three databases and the share must be
in the same replication group.

| Object | Why it is required in the replication group |
| --- | --- |
| `FINANCE_SHARE_DB` | Contains the shared secure view |
| `FINANCE_DB` | Contains the workforce-budget table referenced by the view |
| `PEOPLE_DB` | Contains the department table referenced by the view |
| `FINANCE_TO_PEOPLE_SHARE` | Contains the database, schema, view, and `REFERENCE_USAGE` grants |

Replicating only `FINANCE_SHARE_DB` would copy the secure view but omit its
cross-database dependencies. Every database referenced by the view must move
with it.

Replication works at database level. All eligible contents of `FINANCE_DB`,
`PEOPLE_DB`, and `FINANCE_SHARE_DB` are copied, not only the rows returned by the
secure view. If only a small subset is needed from large source databases,
materialize the approved data in one dedicated sharing database and replicate
that database plus the share.

## Rules before setup

- The source and target must be different Snowflake accounts in the same
  Snowflake organization. The accounts may be in the same or different regions.
- For a cross-region direct-share relay, the target provider account and final
  consumer account must be in the same region. The consumer does not need
  replication enabled.
- An organization administrator must enable replication for the source and
  target accounts.
- For cross-region or cross-cloud replication, confirm that the target location
  satisfies data-residency and regulatory requirements.
- Use a replication group for this workflow. It keeps the databases and share
  together; standalone database replication does not replicate the share.
- A database already enabled for standalone replication with `ALTER DATABASE
  ... ENABLE REPLICATION TO ACCOUNTS` cannot be added directly to a replication
  group. Transition it from standalone replication before creating the group.

Database and share replication are available on all Snowflake editions.
Snowflake blocks replication from a Business Critical account to a lower-edition
target by default. `IGNORE EDITION CHECK` can override that safeguard and is
intentionally omitted from this setup.

## Inspect an existing replication setup

Run the context query in every source and target account. It confirms which
account is active and the one region assigned to that account.

```sql
SELECT
    CURRENT_ORGANIZATION_NAME() AS ORGANIZATION_NAME,
    CURRENT_ACCOUNT_NAME() AS ACCOUNT_NAME,
    CURRENT_REGION() AS SNOWFLAKE_REGION;
```

Representative result from a source account:

| ORGANIZATION_NAME | ACCOUNT_NAME | SNOWFLAKE_REGION |
| --- | --- | --- |
| `YOUR_ORG` | `FINANCE_PROD` | `AWS_US_EAST_1` |

### List the replication groups

```sql
USE ROLE ACCOUNTADMIN;

SHOW REPLICATION GROUPS;
```

Representative raw output from a source account can contain both a local
primary and its related secondary:

| SNOWFLAKE_REGION | ACCOUNT_NAME | NAME | TYPE | IS_PRIMARY | PRIMARY | OBJECT_TYPES | ALLOWED_ACCOUNTS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `AWS_US_EAST_1` | `FINANCE_PROD` | `FINANCE_PEOPLE_RG` | `REPLICATION` | `true` | `YOUR_ORG.FINANCE_PROD.FINANCE_PEOPLE_RG` | `DATABASES, SHARES` | `YOUR_ORG.FINANCE_REPLICA` |
| `AWS_US_WEST_2` | `FINANCE_REPLICA` | `FINANCE_PEOPLE_RG` | `REPLICATION` | `false` | `YOUR_ORG.FINANCE_PROD.FINANCE_PEOPLE_RG` | `NULL` | `NULL` |

This command can return primary and secondary replication groups, failover
groups, and related groups in other enabled accounts. It is not limited to
groups owned by the current account.

If the current source account should own two primary replication groups, filter
the `SHOW` result rather than counting every row:

```sql
SELECT
    "snowflake_region" AS SNOWFLAKE_REGION,
    "account_name" AS ACCOUNT_NAME,
    "name" AS GROUP_NAME,
    "type" AS GROUP_TYPE,
    "is_primary" AS IS_PRIMARY,
    "primary" AS PRIMARY_GROUP,
    "object_types" AS OBJECT_TYPES,
    "allowed_accounts" AS ALLOWED_ACCOUNTS,
    COUNT(*) OVER () AS PRIMARY_GROUP_COUNT
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
WHERE "type" = 'REPLICATION'
  AND LOWER("is_primary") = 'true'
  AND "account_name" = CURRENT_ACCOUNT_NAME()
  AND "name" IN (
      'FINANCE_PEOPLE_RG',
      'LEDGER_PEOPLE_RG'
  )
ORDER BY "name";
```

Representative result confirming two primaries:

| SNOWFLAKE_REGION | ACCOUNT_NAME | GROUP_NAME | GROUP_TYPE | IS_PRIMARY | PRIMARY_GROUP | OBJECT_TYPES | ALLOWED_ACCOUNTS | PRIMARY_GROUP_COUNT |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `AWS_US_EAST_1` | `FINANCE_PROD` | `FINANCE_PEOPLE_RG` | `REPLICATION` | `true` | `YOUR_ORG.FINANCE_PROD.FINANCE_PEOPLE_RG` | `DATABASES, SHARES` | `YOUR_ORG.FINANCE_REPLICA` | `2` |
| `AWS_US_EAST_1` | `FINANCE_PROD` | `LEDGER_PEOPLE_RG` | `REPLICATION` | `true` | `YOUR_ORG.FINANCE_PROD.LEDGER_PEOPLE_RG` | `DATABASES` | `YOUR_ORG.FINANCE_REPLICA` | `2` |

The two rows are two independent primary group definitions. They are not two
primaries for one replication lineage.

| Group row | Meaning |
| --- | --- |
| `IS_PRIMARY = true` | Authoritative group in the source account. Its member objects are writable there. `PRIMARY_GROUP` identifies this source group. |
| `IS_PRIMARY = false` | Secondary group in a target account. `PRIMARY_GROUP` points back to the source group, and replicated member databases are read-only. |

A secondary group can have a different name from its primary. Use
`PRIMARY_GROUP`, not matching names, to identify the lineage.

A replication-group secondary cannot be promoted. Use a failover group when a
secondary must be promotable.

### List the databases and shares inside one group

`SHOW REPLICATION GROUPS` lists the containers. Use the membership commands to
see what a particular group contains:

```sql
SHOW DATABASES IN REPLICATION GROUP FINANCE_PEOPLE_RG;
```

Representative result:

| NAME |
| --- |
| `FINANCE_SHARE_DB` |
| `FINANCE_DB` |
| `PEOPLE_DB` |

A second primary group has its own independent database membership:

```sql
SHOW DATABASES IN REPLICATION GROUP LEDGER_PEOPLE_RG;
```

Representative result:

| NAME |
| --- |
| `LEDGER_DB` |

```sql
SHOW SHARES IN REPLICATION GROUP FINANCE_PEOPLE_RG;
```

Representative result:

| KIND | OWNER_ACCOUNT | NAME | DATABASE_NAME |
| --- | --- | --- | --- |
| `OUTBOUND` | `YOUR_ORG.FINANCE_PROD` | `FINANCE_TO_PEOPLE_SHARE` | `FINANCE_SHARE_DB` |

The database command returns database membership, not tables or rows inside the
databases. The share command returns outbound-share membership. Inbound shares
cannot be added to a replication group. Neither command reports refresh status.

### List database replication relationships

```sql
SHOW REPLICATION DATABASES;
```

Representative database-centric result:

| SNOWFLAKE_REGION | ACCOUNT_NAME | NAME | IS_PRIMARY | PRIMARY | REPLICATION_ALLOWED_TO_ACCOUNTS |
| --- | --- | --- | --- | --- | --- |
| `AWS_US_EAST_1` | `SOURCE_ACCOUNT` | `LEDGER_DB` | `true` | `YOUR_ORG.SOURCE_ACCOUNT.LEDGER_DB` | `YOUR_ORG.TARGET_ACCOUNT` |
| `AWS_US_WEST_2` | `TARGET_ACCOUNT` | `LEDGER_DB` | `false` | `YOUR_ORG.SOURCE_ACCOUNT.LEDGER_DB` | `NULL` |

This output answers, "Which database is primary or secondary, and where is its
primary?" It does not answer, "Which replication group contains this database?"
Use `SHOW DATABASES IN REPLICATION GROUP <GROUP_NAME>` for that question.

All four `SHOW` commands are privilege-filtered. A missing row can mean that the
current role lacks visibility, not that the group, database, or share is absent.

| Command | What it returns | What it does not establish |
| --- | --- | --- |
| `SHOW REPLICATION GROUPS` | Visible group topology, primary or secondary role, source link, object types, target accounts, and schedule | Member databases, member shares, or successful refresh |
| `SHOW DATABASES IN REPLICATION GROUP <GROUP_NAME>` | Visible database members of one group | Tables, rows, or refresh success |
| `SHOW SHARES IN REPLICATION GROUP <GROUP_NAME>` | Visible outbound-share members of one group | Consumer imports or refresh success |
| `SHOW REPLICATION DATABASES` | Visible primary and secondary database relationships | Replication-group membership or refresh success |

## Example: replicate the Finance share into the People Analytics region

| Item | Name |
| --- | --- |
| Source provider account | `YOUR_ORG.FINANCE_PROD` |
| Destination-region provider account | `YOUR_ORG.FINANCE_REPLICA` |
| Local consumer account | `YOUR_ORG.PEOPLE_ANALYTICS` |
| Replication group | `FINANCE_PEOPLE_RG` |
| Databases | `FINANCE_SHARE_DB`, `FINANCE_DB`, `PEOPLE_DB` |
| Share | `FINANCE_TO_PEOPLE_SHARE` |
| Consumer imported database | `FINANCE_SHARED_DB` |
| Refresh interval | 15 minutes |

### 1. Prepare the share in the source account

Complete steps 1 through 5 in the
[secure data sharing example](secure-data-sharing.md#example-finance-shares-workforce-budget-data-with-people-analytics).
This creates the secure view, share, and provider grants in
`YOUR_ORG.FINANCE_PROD`.

Do not run step 6 there. `YOUR_ORG.PEOPLE_ANALYTICS` is in another region, so it
must be added to the replicated share in `YOUR_ORG.FINANCE_REPLICA` after the
first refresh.

### 2. Enable replication for the provider accounts

Run from an account where the `ORGADMIN` role is enabled:

```sql
USE ROLE ORGADMIN;

SELECT SYSTEM$GLOBAL_ACCOUNT_SET_PARAMETER(
    'YOUR_ORG.FINANCE_PROD',
    'ENABLE_ACCOUNT_DATABASE_REPLICATION',
    'true'
) AS STATUS;

SELECT SYSTEM$GLOBAL_ACCOUNT_SET_PARAMETER(
    'YOUR_ORG.FINANCE_REPLICA',
    'ENABLE_ACCOUNT_DATABASE_REPLICATION',
    'true'
) AS STATUS;
```

Example result for each function call:

| STATUS |
| --- |
| `["SUCCESS"]` |

Verify the enabled accounts from either replication-enabled provider account:

```sql
USE ROLE ACCOUNTADMIN;

SHOW REPLICATION ACCOUNTS;
```

Relevant output columns:

| SNOWFLAKE_REGION | ACCOUNT_NAME | ORGANIZATION_NAME |
| --- | --- | --- |
| `AWS_US_EAST_1` | `FINANCE_PROD` | `YOUR_ORG` |
| `AWS_US_WEST_2` | `FINANCE_REPLICA` | `YOUR_ORG` |

The region identifiers are examples. The important result is that both provider
accounts appear and their regions are different.

### 3. Create the primary replication group

Run in `YOUR_ORG.FINANCE_PROD`:

```sql
USE ROLE ACCOUNTADMIN;

CREATE REPLICATION GROUP FINANCE_PEOPLE_RG
    OBJECT_TYPES = DATABASES, SHARES
    ALLOWED_DATABASES =
        FINANCE_SHARE_DB,
        FINANCE_DB,
        PEOPLE_DB
    ALLOWED_SHARES =
        FINANCE_TO_PEOPLE_SHARE
    ALLOWED_ACCOUNTS =
        YOUR_ORG.FINANCE_REPLICA
    REPLICATION_SCHEDULE = '15 MINUTE';
```

`ALLOWED_ACCOUNTS` names the provider-controlled replication account, not the
People Analytics consumer.

Verify the group:

```sql
SHOW REPLICATION GROUPS;
```

Relevant output columns:

| SNOWFLAKE_REGION | ACCOUNT_NAME | NAME | TYPE | IS_PRIMARY | PRIMARY | OBJECT_TYPES | ALLOWED_ACCOUNTS | REPLICATION_SCHEDULE |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `AWS_US_EAST_1` | `FINANCE_PROD` | `FINANCE_PEOPLE_RG` | `REPLICATION` | `true` | `YOUR_ORG.FINANCE_PROD.FINANCE_PEOPLE_RG` | `DATABASES, SHARES` | `YOUR_ORG.FINANCE_REPLICA` | `15 MINUTE` |

Verify the database and share membership:

```sql
SHOW DATABASES IN REPLICATION GROUP FINANCE_PEOPLE_RG;
```

Relevant output:

| NAME |
| --- |
| `FINANCE_SHARE_DB` |
| `FINANCE_DB` |
| `PEOPLE_DB` |

```sql
SHOW SHARES IN REPLICATION GROUP FINANCE_PEOPLE_RG;
```

Relevant output columns:

| KIND | OWNER_ACCOUNT | NAME | DATABASE_NAME |
| --- | --- | --- | --- |
| `OUTBOUND` | `YOUR_ORG.FINANCE_PROD` | `FINANCE_TO_PEOPLE_SHARE` | `FINANCE_SHARE_DB` |

### 4. Create the secondary group and verify the initial refresh

Run in `YOUR_ORG.FINANCE_REPLICA`:

```sql
USE ROLE ACCOUNTADMIN;

CREATE REPLICATION GROUP FINANCE_PEOPLE_RG
    AS REPLICA OF
        YOUR_ORG.FINANCE_PROD.FINANCE_PEOPLE_RG;
```

Creating the secondary group automatically starts its initial refresh. The
15-minute schedule on the primary group handles later refreshes.

Verify the secondary group:

```sql
SHOW REPLICATION GROUPS;
```

Relevant output columns:

| SNOWFLAKE_REGION | ACCOUNT_NAME | NAME | TYPE | IS_PRIMARY | PRIMARY | REPLICATION_SCHEDULE | SECONDARY_STATE |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `AWS_US_WEST_2` | `FINANCE_REPLICA` | `FINANCE_PEOPLE_RG` | `REPLICATION` | `false` | `YOUR_ORG.FINANCE_PROD.FINANCE_PEOPLE_RG` | `15 MINUTE` | `STARTED` |

Check the latest refresh phase:

```sql
SELECT
    PHASE_NAME,
    START_TIME,
    END_TIME,
    ERROR
FROM TABLE(
    FINANCE_SHARE_DB.INFORMATION_SCHEMA.REPLICATION_GROUP_REFRESH_HISTORY(
        'FINANCE_PEOPLE_RG'
    )
)
ORDER BY START_TIME DESC
LIMIT 1;
```

Example result:

| PHASE_NAME | START_TIME | END_TIME | ERROR |
| --- | --- | --- | --- |
| `COMPLETED` | `2026-08-12 10:00:00 -0500` | `2026-08-12 10:02:14 -0500` | `NULL` |

Do not add the consumer until the newest phase is `COMPLETED`. A different value
means the refresh is still running, failed, or was canceled.

To request a later synchronization without waiting for the schedule, run this
in `YOUR_ORG.FINANCE_REPLICA`:

```sql
ALTER REPLICATION GROUP FINANCE_PEOPLE_RG REFRESH;
```

### 5. Add the local consumer to the replicated share

Run in `YOUR_ORG.FINANCE_REPLICA`:

```sql
ALTER SHARE FINANCE_TO_PEOPLE_SHARE
    ADD ACCOUNTS = YOUR_ORG.PEOPLE_ANALYTICS;

SHOW SHARES LIKE 'FINANCE_TO_PEOPLE_SHARE';
```

Relevant output columns in the destination-region provider account:

| KIND | OWNER_ACCOUNT | NAME | DATABASE_NAME | TO |
| --- | --- | --- | --- | --- |
| `OUTBOUND` | `YOUR_ORG.FINANCE_REPLICA` | `FINANCE_TO_PEOPLE_SHARE` | `FINANCE_SHARE_DB` | `YOUR_ORG.PEOPLE_ANALYTICS` |

The local consumer list on the replicated share is preserved by later refreshes.

### 6. Import the regional share

Run in `YOUR_ORG.PEOPLE_ANALYTICS`:

```sql
USE ROLE ACCOUNTADMIN;

SHOW SHARES LIKE 'FINANCE_TO_PEOPLE_SHARE';
```

Relevant output columns:

| KIND | OWNER_ACCOUNT | NAME |
| --- | --- | --- |
| `INBOUND` | `YOUR_ORG.FINANCE_REPLICA` | `FINANCE_TO_PEOPLE_SHARE` |

Create the consumer database from the regional provider account, not from
`YOUR_ORG.FINANCE_PROD`:

```sql
CREATE DATABASE FINANCE_SHARED_DB
    FROM SHARE
        YOUR_ORG.FINANCE_REPLICA.FINANCE_TO_PEOPLE_SHARE;

SHOW DATABASES LIKE 'FINANCE_SHARED_DB';
```

Relevant output columns:

| NAME | ORIGIN | OWNER |
| --- | --- | --- |
| `FINANCE_SHARED_DB` | `YOUR_ORG.FINANCE_REPLICA.FINANCE_TO_PEOPLE_SHARE` | `ACCOUNTADMIN` |

The imported database does not need to be recreated after replication refreshes.
Continue with [granting consumer access](secure-data-sharing.md#9-grant-consumer-access)
and [querying the secure view](secure-data-sharing.md#10-query-the-shared-view).
