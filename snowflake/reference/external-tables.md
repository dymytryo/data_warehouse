# Snowflake external tables

An external table lets Snowflake query files in external storage without
loading those files into a native Snowflake table. The table reads through an
external stage.

## 1. Create the external stage

```sql
CREATE OR REPLACE STAGE EVENTS_STAGE
    URL = 's3://example-bucket/events/'
    STORAGE_INTEGRATION = S3_INTEGRATION;
```

## 2. Create the external table

For Parquet files, columns are derived from the file's `VALUE` object.

```sql
CREATE OR REPLACE EXTERNAL TABLE EXT.EVENTS (
    EVENT_ID NUMBER AS (VALUE:event_id::NUMBER),
    EVENT_TIME TIMESTAMP_NTZ AS (VALUE:event_time::TIMESTAMP_NTZ)
)
LOCATION = @EVENTS_STAGE
FILE_FORMAT = (TYPE = PARQUET)
AUTO_REFRESH = FALSE;
```

## 3. Refresh and query

Run a manual refresh when `AUTO_REFRESH` is disabled.

```sql
ALTER EXTERNAL TABLE EXT.EVENTS REFRESH;

SELECT *
FROM EXT.EVENTS
LIMIT 10;
```

Reference: [Snowflake `CREATE EXTERNAL TABLE`](https://docs.snowflake.com/en/sql-reference/sql/create-external-table)
