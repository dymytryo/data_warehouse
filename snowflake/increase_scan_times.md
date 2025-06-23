```sql
DATE WAREHOUSE RISK_WH
ALTER WAREHOUSE RISK_WH SET STATEMENT_TIMEOUT_IN_SECONDS = 144000; 
```
You can check if this was set here: 
```sql 
SHOW PARAMETERS IN WAREHOUSE RISK_WH; 
```

```sql
SHOW PARAMETERS LIKE 'STATEMENT_TIMEOUT_IN_SECONDS'
```

```sql
USE WAREHOUSE RISK_WH;
```

```sql
SHOW PARAMETERS 'STATEMENT_TIMEOUT_IN_SECONDS' IN ACCOUNT; 
```

You can set this on an account level: 
```sql
ALTER ACCOUNT SET STATEMENT_TIMEOUT_IN_SECONDS = 144400;
```

```sql
-- Session-only (applies to the connection you’re in)
ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = 28_800;   -- 8 h

-- Warehouse default (covers every session that uses the warehouse)
ALTER WAREHOUSE my_wh
  SET STATEMENT_TIMEOUT_IN_SECONDS = 28_800;

-- Account-wide (last resort; needs ACCOUNTADMIN)
ALTER ACCOUNT SET STATEMENT_TIMEOUT_IN_SECONDS = 172_800;  -- 48 h
```
