-- macros/collect_all_sf_stats.sql

{% macro collect_all_sf_stats() %}
    {%- set all_tables = run_query(
        "
        SELECT 'snowflake' AS catalog, table_schema, table_name
        FROM snowflake.information_schema.tables
        WHERE table_schema LIKE '\\_%' ESCAPE '\\'
        UNION ALL
        SELECT 'snowflake_pii' AS catalog, table_schema, table_name
        FROM snowflake_pii.information_schema.tables
        WHERE table_schema LIKE '\\_%' ESCAPE '\\'
        "
    ) %}

    {% for row in all_tables %}
        {% set table = row['catalog'] ~ '.' ~ row['table_schema'] ~ '.' ~ row['table_name'] %}
        {{ log("Collecting stats: " ~ table, info=True) }}
        {% do run_query("ALTER TABLE " ~ table ~ " EXECUTE collect_statistics;") %}
    {% endfor %}
{% endmacro %}

-- Execute with command below
{# dbt run-operation collect_all_sf_stats #}
