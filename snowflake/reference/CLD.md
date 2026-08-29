# Problem it solves
You have Iceberg tables on S3, catalogued in an external Iceberg REST catalog (Polaris). You want to SELECT them from Snowflake without hand-defining each table or re-declaring them every time the catalog adds a table. CLD automates that.

# CLD 
`Catalog-Linked Database`
 A Snowflake database whose contents are a live, read-only mirror of external-catalog namespaces. You link it to a catalog + a list of namespaces; Snowflake auto-discovers every table in them and keeps the set in sync on a poll interval. ICEBERG_PROD_US is CAP's CLD.

# Objects underneath

`CATALOG INTEGRATION` - connection to Polaris (receiving instance runs `CREATE CATALOG INTEGRATION`, polaris instance runs `GRANT LOAD_TABLE`, etc.)
CLD (<ICEBERG_PROD>) - a new database in receiving instance that is read-only with an `ALLOWED_NAMESPACES` from Polaris
Storage access - `VENDED CREDENTIALS` 

# Namespace -> Schema mapping
Each Polaris namespace becomes a Snowflake schema
Each table in Polaris -> read-only Iceberg table in receiving catalog

Add a namespace to mirror:
```sql
ALTER DATABASE ICEBERG_PROD
  UPDATE LINKED_CATALOG ADD ('<schema-name>') TO ALLOWED_NAMESPACES;
```
Read (quoted lowercase; catalog names are case-sensitive)
```sql
SELECT * FROM ICEBERG_PROD_US."ledger_lake"."ledgerentry" LIMIT 10;
```

```sql
-- health / why-didn't-my-table-appear
SELECT SYSTEM$CATALOG_LINK_STATUS('<CLD-name>');
SELECT SYSTEM$CATALOG_LINK_STATUS('ICEBERG_PROD');
```
```
{"failureDetails":[],"executionState":"RUNNING","lastLinkAttemptStartTime":"2026-08-28T23:55:35.719Z"}
```
-- force a re-sync
```sql
ALTER DATABASE ICEBERG_PROD_US RESUME DISCOVERY;
```

