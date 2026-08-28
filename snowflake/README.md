# Snowflake acquisition data integration

This case study shows how BILL consolidated Divvy's acquired analytics workloads
from a standalone Snowflake estate into BILL's Starburst/Trino lakehouse on
Apache Iceberg. The program covered ingestion, dbt model conversion, object
mapping, parity testing, business intelligence (BI) repointing, cost control,
and controlled Snowflake decommissioning.

Because the data supported financial reporting, the migration operated under
Sarbanes-Oxley (SOX) controls. Every in-scope object needed an owner, a mapped
destination, validation evidence, and a reversible cutover record.

## Results

| Measure | Approximate result |
| --- | ---: |
| Snowflake run rate addressed | About $450 per day |
| Annualized cost opportunity | About $165K per year |
| Snowflake consumption at the planning baseline | About 900 credits per week |
| Iceberg storage amplification corrected | About 3x |
| Objects tracked | About 950 |
| Migration progress at the reporting snapshot | About 80% complete |

## Architecture

~~~mermaid
flowchart LR
    subgraph Sources[Operational sources]
        DB[(Databases)]
        SaaS[SaaS applications]
        Files[Files and object storage]
    end

    subgraph Ingestion[Ingestion]
        Stream[Streaming]
        Batch[Managed and custom batch jobs]
    end

    subgraph Lakehouse[Consolidated lakehouse]
        Raw[Raw Iceberg tables]
        Dbt[dbt transformations]
        Curated[Curated Iceberg tables]
        Maintain[Compaction and retention]
    end

    Trino[Starburst / Trino]
    BI[BI and reporting]
    Snowflake[(Snowflake transition layer)]

    DB --> Stream --> Raw
    SaaS --> Batch --> Raw
    Files --> Batch
    Raw --> Dbt --> Curated
    Maintain --> Curated
    Curated --> Trino --> BI
    Curated -. temporary compatibility .-> Snowflake -. repointed .-> BI
~~~

Iceberg separated storage from compute and made the data available through
Starburst/Trino. Temporary Snowflake compatibility remained only for consumers
that could not be repointed in the same release.

## Migration controls

~~~mermaid
flowchart TD
    Inventory[Inventory source objects] --> Classify{Classify object}
    Classify -->|Ingested source| SourceMap[Map source exposure]
    Classify -->|dbt model or snapshot| ModelMap[Map transformed object]
    Classify -->|Unused or broken| Review[Dependency and owner review]
    SourceMap --> Availability[Check target availability]
    ModelMap --> Availability
    Availability --> Shape[Compare columns and data types]
    Shape --> Composition[Compare counts, keys, nulls, ranges, and totals]
    Composition --> Gate{Within tolerance?}
    Gate -->|No| Remediate[Investigate and rerun]
    Remediate --> Availability
    Gate -->|Yes| Evidence[Record evidence and approval]
    Review --> Evidence
    Evidence --> Repoint[Repoint consumers]
    Repoint --> Observe[Observe and retain rollback window]
    Observe --> Retire[Retire source object]
~~~

The control design used three levels of evidence:

1. **Availability:** confirm that the expected target object exists and can be
   queried.
2. **Shape:** compare columns and normalized data types, including columns that
   exist on only one side.
3. **Composition:** compare row counts, distinct keys, null rates, date ranges,
   boolean distributions, and numeric totals within agreed tolerances.

The object tracker combined those checks into a single migration status for
about 950 objects. At the retained reporting snapshot, about 80% were complete.
The tracker also made exceptions explicit instead of hiding them in the overall
percentage.

## Cost and storage controls

The planning baseline showed about 900 Snowflake credits per week and a run rate
of about $450 per day, or about $165K annualized. Consumption reporting by
warehouse and workload identified the remaining Snowflake users and ordered the
cutover backlog by financial impact.

The target lakehouse also needed active storage management. Unexpired snapshots,
small files, and orphan files had expanded Iceberg storage to about 3x the
governed footprint. The maintenance pattern in
[iceberg_maintenance.md](iceberg_maintenance.md) adds compaction, optimizer
statistics, snapshot expiration, orphan cleanup, row-count protection, and an
optional audit record to each physical dbt build.

## Snowflake reference notes

Reusable notes on Snowflake architecture, storage, table types, recovery,
performance, and data sharing live in [reference/](reference/README.md). They are
kept separate from the migration-specific assets below.

## Portfolio assets

| File | Purpose |
| --- | --- |
| [migration_parity.py](migration_parity.py) | Configurable row and column parity checks with data-loss risk flags |
| [object_availability_report.sql](object_availability_report.sql) | Trino query that inventories source objects, derives target names, and calculates migration status |
| [object_availability_report.yml](object_availability_report.yml) | Column-level documentation for the availability report |
| [object_copy_removal_runbook.md](object_copy_removal_runbook.md) | SOX-oriented copy, repoint, removal, and rollback procedure |
| [iceberg_maintenance.md](iceberg_maintenance.md) | dbt maintenance macro and operating guidance for Iceberg |
| [stats_collection/](stats_collection/) | Parallel collection of table statistics for query planning |
| [increase_scan_times.md](increase_scan_times.md) | Per-model guardrail for unusually wide Trino queries |

## Repository layout

~~~text
snowflake/
├── README.md
├── reference/
│   ├── README.md
│   ├── architecture-and-micro-partitions.md
│   ├── cancel_query.sql
│   ├── data-retention-and-backups.md
│   ├── external-tables.md
│   ├── micro-partitions-and-clustering.md
│   ├── replication-groups-for-secure-data-sharing.md
│   ├── secure-data-sharing.md
│   ├── table-and-view-types.md
│   └── zero-copy-cloning.md
├── migration_parity.py
├── object_availability_report.sql
├── object_availability_report.yml
├── object_copy_removal_runbook.md
├── iceberg_maintenance.md
├── increase_scan_times.md
├── snowflauseful_queries.md
├── GRANTS.md
├── SOS.md
├── data_retention.sql
├── iceberg.md
├── migration/
│   └── .gitlab-ci.yml
└── stats_collection/
~~~
