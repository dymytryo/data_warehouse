# Snowflake reference notes

These notes explain Snowflake storage, table and view behavior, recovery,
performance, and data-sharing features. They are reusable technical references,
separate from the acquisition-integration case study in the parent folder.

| Note | Covers |
| --- | --- |
| [Architecture and micro-partitions](architecture-and-micro-partitions.md) | Shared-data architecture, services, warehouses, storage, caching, pruning, and billing boundaries |
| [Table and view types](table-and-view-types.md) | Permanent, transient, temporary, and external tables; standard, secure, and materialized views |
| [Hybrid tables](hybrid-tables.md) | Row-store architecture, enforced constraints, indexes, transactions, limitations, recovery, and verification |
| [Micro-partitions and clustering](micro-partitions-and-clustering.md) | Pruning, clustering depth, clustering keys, reclustering, and query evidence |
| [Data retention and backups](data-retention-and-backups.md) | Time Travel, Fail-safe, `UNDROP`, cloning, dbt replacement behavior, and backup choices |
| [External tables](external-tables.md) | External stages, file formats, external-table creation, metadata refresh, and verification |
| [Zero-copy cloning](zero-copy-cloning.md) | Shared micro-partitions, independent changes, storage growth, permissions, and recovery |
| [Secure data sharing](secure-data-sharing.md) | Provider shares, consumer databases, secure views, grants, and validation |
| [Replication groups for secure sharing](replication-groups-for-secure-data-sharing.md) | Cross-region replication, failover, refresh, monitoring, and consumer cutover |
| [Cancel a query](cancel_query.sql) | Cancelling a running query by query identifier |
