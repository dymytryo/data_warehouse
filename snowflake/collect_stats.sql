-- macros/collect_all_sf_stats.sql

{% macro collect_all_sf_stats() %}
    {# Get tables from snowflake #}
    {% set sf_tables = run_query(
        "SELECT table_schema, table_name FROM snowflake.information_schema.tables WHERE table_schema LIKE '\\_%' ESCAPE '\\'"
    ) %}
    {# Get tables from snowflake_pii #}
    {% set pii_tables = run_query(
        "SELECT table_schema, table_name FROM snowflake_pii.information_schema.tables WHERE table_schema LIKE '\\_%' ESCAPE '\\'"
    ) %}

    {% for row in sf_tables %}
        {% set table = "snowflake." ~ row['table_schema'] ~ '.' ~ row['table_name'] %}
        {{ log("Collecting stats: " ~ table, info=True) }}
        {% do run_query("ALTER TABLE " ~ table ~ " EXECUTE collect_statistics;") %}
    {% endfor %}

    {% for row in pii_tables %}
        {% set table = "snowflake_pii." ~ row['table_schema'] ~ '.' ~ row['table_name'] %}
        {{ log("Collecting stats: " ~ table, info=True) }}
        {% do run_query("ALTER TABLE " ~ table ~ " EXECUTE collect_statistics;") %}
    {% endfor %}
{% endmacro %}

-- Execute with command below
{# dbt run-operation collect_all_sf_stats #}
