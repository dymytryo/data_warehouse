-- Object availability report for a Snowflake-to-Iceberg migration.
--
-- Catalog aliases separate the legacy inventory, lakehouse source exposure,
-- and governed Iceberg destination.

WITH
source_snapshots AS (
    SELECT
        schema_name AS source_schema,
        alias AS source_table
    FROM legacy_warehouse.metadata.dbt_snapshots
    GROUP BY
        schema_name,
        alias
),

source_objects AS (
    SELECT DISTINCT
        tables.table_schema AS source_schema,
        tables.table_name AS source_table,
        CASE LOWER(tables.table_type)
            WHEN 'base table' THEN 'table'
            WHEN 'materialized view' THEN 'materialized_view'
            ELSE LOWER(tables.table_type)
        END AS source_object_type,
        snapshots.source_table IS NOT NULL AS is_snapshot,
        SUBSTRING(tables.table_schema, 1, 1) = '_' AS is_ingestion,
        CASE
            WHEN SUBSTRING(tables.table_schema, 1, 1) = '_'
                THEN SUBSTRING(tables.table_schema, 2)
            ELSE tables.table_schema
        END AS normalized_source_schema
    FROM legacy_warehouse.information_schema.tables AS tables
    LEFT JOIN source_snapshots AS snapshots
        ON snapshots.source_schema = tables.table_schema
       AND snapshots.source_table = tables.table_name
    WHERE tables.table_schema NOT IN ('information_schema', 'metadata')
),

source_dbt_models AS (
    SELECT
        schema_name AS source_schema,
        alias AS source_table,
        MIN(name) AS dbt_model_name,
        MIN(original_path) AS dbt_model_path
    FROM legacy_warehouse.metadata.dbt_models
    WHERE schema_name <> 'metadata'
    GROUP BY
        schema_name,
        alias
),

source_inventory AS (
    SELECT
        objects.*,
        models.dbt_model_name,
        models.dbt_model_path,
        models.source_table IS NOT NULL AS is_managed_by_dbt,
        CASE
            WHEN objects.is_ingestion THEN 'staging'
            ELSE 'core'
        END AS expected_target_schema,
        CASE
            WHEN objects.is_ingestion
                THEN
                    'stg_source__'
                    || objects.normalized_source_schema
                    || '_'
                    || objects.source_table
            ELSE
                'migrated_'
                || objects.normalized_source_schema
                || '_'
                || COALESCE(models.source_table, objects.source_table)
        END AS expected_target_table,
        CASE
            WHEN objects.is_ingestion
                THEN 'source_' || objects.normalized_source_schema
            ELSE objects.source_schema
        END AS expected_source_schema,
        objects.source_table AS expected_source_table
    FROM source_objects AS objects
    LEFT JOIN source_dbt_models AS models
        ON models.source_schema = objects.source_schema
       AND models.source_table = objects.source_table
),

lakehouse_source_objects AS (
    SELECT DISTINCT
        table_schema AS exposed_source_schema,
        table_name AS exposed_source_table,
        CASE LOWER(table_type)
            WHEN 'base table' THEN 'table'
            WHEN 'materialized view' THEN 'materialized_view'
            ELSE LOWER(table_type)
        END AS exposed_source_object_type
    FROM source_lakehouse.information_schema.tables
),

target_objects AS (
    SELECT DISTINCT
        table_schema AS target_schema,
        table_name AS target_table,
        CASE LOWER(table_type)
            WHEN 'base table' THEN 'table'
            WHEN 'materialized view' THEN 'materialized_view'
            ELSE LOWER(table_type)
        END AS target_object_type
    FROM analytics_lakehouse.information_schema.tables
    WHERE table_schema IN ('staging', 'core')
),

target_dbt_models AS (
    SELECT
        schema_name AS target_schema,
        alias AS target_table,
        MIN(name) AS target_dbt_model_name,
        MIN(original_path) AS target_dbt_model_path
    FROM analytics_lakehouse.metadata.dbt_models
    WHERE schema_name IN ('staging', 'core')
    GROUP BY
        schema_name,
        alias
),

target_inventory AS (
    SELECT
        objects.*,
        models.target_table IS NOT NULL AS is_target_managed_by_dbt,
        models.target_dbt_model_name,
        models.target_dbt_model_path
    FROM target_objects AS objects
    LEFT JOIN target_dbt_models AS models
        ON models.target_schema = objects.target_schema
       AND models.target_table = objects.target_table
),

availability AS (
    SELECT
        source.*,
        exposed.exposed_source_schema,
        exposed.exposed_source_table,
        exposed.exposed_source_object_type,
        exposed.exposed_source_table IS NOT NULL AS is_source_available,
        target.target_schema,
        target.target_table,
        target.target_object_type,
        target.is_target_managed_by_dbt,
        target.target_dbt_model_name,
        target.target_dbt_model_path,
        target.target_table IS NOT NULL AS is_target_available
    FROM source_inventory AS source
    LEFT JOIN lakehouse_source_objects AS exposed
        ON exposed.exposed_source_schema = source.expected_source_schema
       AND exposed.exposed_source_table = source.expected_source_table
    LEFT JOIN target_inventory AS target
        ON target.target_schema = source.expected_target_schema
       AND target.target_table = source.expected_target_table
)

SELECT
    'legacy_warehouse' AS source_catalog,
    source_schema,
    source_table,
    source_object_type,
    is_snapshot,
    is_ingestion,
    is_managed_by_dbt,
    dbt_model_name,
    dbt_model_path,
    expected_source_schema,
    expected_source_table,
    exposed_source_schema,
    exposed_source_table,
    exposed_source_object_type,
    is_source_available,
    expected_target_schema,
    expected_target_table,
    target_schema,
    target_table,
    target_object_type,
    is_target_managed_by_dbt,
    target_dbt_model_name,
    target_dbt_model_path,
    is_target_available,
    CASE
        WHEN is_ingestion
            THEN is_source_available AND is_target_available
        ELSE is_target_available
    END AS migration_status
FROM availability;
