# Iceberg storage maintenance

Apache Iceberg preserves immutable data and metadata files across table commits.
Without an operating routine, small files, retained snapshots, and orphan files
can increase scan cost and storage. During the migration, that amplification
reached about 3x the governed footprint.

The remediation attached maintenance to physical dbt builds and kept retention
settings configurable by environment.

## dbt configuration

~~~yaml
models:
  analytics:
    +post-hook:
      - "{{ run_iceberg_maintenance() }}"
~~~

Models can opt out during incident response with
skip_iceberg_maintenance: true.

## Maintenance macro

~~~sql
{% macro run_iceberg_maintenance() %}
  {% set physical_model =
      model.config.materialized in ['table', 'incremental']
      or model.resource_type == 'snapshot' %}

  {% if execute
      and physical_model
      and not model.config.get('skip_iceberg_maintenance', false) %}

    {% set before_result = run_query('SELECT COUNT(*) FROM ' ~ this) %}
    {% set rows_before = before_result.columns[0].values()[0] %}
    {% set target_size = var('iceberg_target_file_size', '512MB') %}
    {% set retention = var('iceberg_retention_threshold', '7d') %}

    {% do run_query(
      'ALTER TABLE ' ~ this
      ~ " EXECUTE optimize(file_size_threshold => '" ~ target_size ~ "')"
    ) %}
    {% do run_query('ANALYZE ' ~ this) %}
    {% do run_query('ALTER TABLE ' ~ this ~ ' EXECUTE optimize_manifests') %}
    {% do run_query(
      'ALTER TABLE ' ~ this
      ~ " EXECUTE expire_snapshots(retention_threshold => '" ~ retention ~ "')"
    ) %}
    {% do run_query(
      'ALTER TABLE ' ~ this
      ~ " EXECUTE remove_orphan_files(retention_threshold => '" ~ retention ~ "')"
    ) %}

    {% set after_result = run_query('SELECT COUNT(*) FROM ' ~ this) %}
    {% set rows_after = after_result.columns[0].values()[0] %}

    {% if rows_before != rows_after %}
      {{ exceptions.raise_compiler_error(
        'Iceberg maintenance changed the row count for ' ~ this
      ) }}
    {% endif %}

    {% set audit_relation = var('iceberg_maintenance_audit_relation', none) %}
    {% if audit_relation %}
      {% do run_query(
        'INSERT INTO ' ~ audit_relation
        ~ ' (table_name, run_timestamp, rows_before, rows_after) VALUES ('
        ~ "'" ~ this ~ "', current_timestamp, "
        ~ rows_before ~ ', ' ~ rows_after ~ ')'
      ) %}
    {% endif %}
  {% endif %}

  {{ return('SELECT 1') }}
{% endmacro %}
~~~

The row count is captured before any maintenance operation and checked again
after cleanup. This correct ordering prevents a false control in which both
counts are taken after maintenance.

## Operating sequence

| Step | Operation | Control purpose |
| --- | --- | --- |
| 1 | Compact small files | Reduce file-open overhead and improve scan efficiency |
| 2 | Refresh statistics | Give the Trino optimizer current cardinality estimates |
| 3 | Optimize manifests | Reduce metadata planning overhead |
| 4 | Expire old snapshots | Release metadata and data files outside the approved recovery window |
| 5 | Remove orphan files | Delete files no live snapshot references |
| 6 | Compare row counts | Fail the build if maintenance changes logical data |
| 7 | Record the run | Preserve optional table, time, and before/after evidence |

Retention must exceed the longest expected write duration and comply with the
platform's recovery policy. Test procedure names and parameters against the
deployed Trino or Starburst Iceberg connector before enabling the hook.
