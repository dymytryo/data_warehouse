# Snowflake architecture and micro-partitions

## What Snowflake is

Snowflake is a managed cloud data platform that separates persistent storage
from compute. Standard Snowflake tables are stored centrally in cloud object
storage rather than copied for each warehouse. Independent compute clusters,
called virtual warehouses, run queries and data-loading work against that
shared data.

This design is described as a multi-cluster, shared-data architecture. Storage
and compute can scale independently, so each workload can use the warehouse
size and schedule it needs.

## How the three layers work

```text
Users, business intelligence tools, and applications
                         |
                         v
+-------------------------------------------------------+
| Cloud services                                        |
| Control plane, metadata, and coordination             |
+-------------------------------------------------------+
                  | dispatches work
          +-------+-------------------+
          v                           v
+----------------------+    +----------------------+
| Virtual warehouse A  |    | Virtual warehouse B  |
| Independent compute  |    | Independent compute  |
+----------+-----------+    +-----------+----------+
           |                            |
           +-------------+--------------+
                         v
+-------------------------------------------------------+
| Database storage                                      |
| Shared, compressed micro-partitions in cloud storage  |
+-------------------------------------------------------+
```

| Layer | Main responsibility |
| --- | --- |
| Database storage | Stores table data in object storage provided by Amazon Web Services (AWS), Microsoft Azure, or Google Cloud. Storage grows independently of compute. |
| Compute (query processing) | Virtual warehouses provide the processing power, memory, and temporary storage used for queries and data loading. Each warehouse can resume, suspend, and resize independently. |
| Cloud services | Acts as the control plane, or the brain of Snowflake. It manages authentication, access control, metadata, transactions, query parsing, optimization, and work dispatch. |

Multiple warehouses can query the same centrally stored table at the same time.
They share the table's micro-partitions but do not compete for one another's
compute resources. Queries assigned to the same warehouse do share that
warehouse's resources and may queue when it is busy.

Storage consumption and warehouse compute are measured separately. A table
remains available in storage when its warehouses are suspended. A suspended
warehouse does not consume warehouse credits, but the stored data remains
billable.

## How Snowflake stores table data

Users work with logical tables made of rows and columns. For standard Snowflake
tables, Snowflake reorganizes the loaded data into its proprietary, compressed,
columnar format and stores it in units called micro-partitions.

In the diagrams, `MP` means micro-partition.

```text
What the user sees                 What Snowflake manages

+----------------------+          +-----------------------------+
| Logical table        |  query   | Cloud services metadata     |
| Rows and columns     +--------->| Table -> MP-1, MP-2, MP-3   |
+----------------------+          +--------------+--------------+
                                                 |
                                                 v
                                  Cloud object storage
                                  (transparent to the user)

                                  +--------+ +--------+ +--------+
                                  | MP-1   | | MP-2   | | MP-3   |
                                  |columns | |columns | |columns |
                                  +--------+ +--------+ +--------+
```

The internal files and their locations are transparent to users. Snowflake
uses table metadata to find the required micro-partitions; users do not access
or manage those files directly.

A micro-partition typically contains 50 megabytes (MB) to 500 MB of
uncompressed data. Its physical footprint is smaller because Snowflake
compresses the data before writing it to cloud storage. Within each
micro-partition, values are stored by column so a query can read only the
columns it needs.

Snowflake initially creates micro-partitions according to the order in which
data is inserted or loaded. Related values can therefore span several
micro-partitions, and value ranges can overlap. Allowing those ranges to
overlap, combined with small, automatically sized micro-partitions, helps reduce
the partition skew associated with manually defined static partitions.

## What happens when data changes

Micro-partitions are immutable. When an `UPDATE`, `DELETE`, or similar change
affects rows inside a micro-partition, Snowflake does not edit that partition in
place. It writes a replacement and changes the table metadata to reference the
current set.

The following is a simplified state change:

| State | Physical behavior |
| --- | --- |
| Before | Table metadata points to `MP-1` and `MP-2`. |
| Operation | An update affects rows in `MP-2`. Snowflake reads the affected data and writes replacement `MP-3`. |
| After | Table metadata points to `MP-1` and `MP-3`. `MP-2` is marked deleted and can remain under the table's Time Travel retention. Permanent tables can retain it further for Fail-safe. |

Until an older micro-partition leaves the applicable retention periods, it can
increase storage consumption alongside its replacement.

This replacement behavior is also the storage foundation for features such as
Time Travel and [zero-copy cloning](zero-copy-cloning.md).

## How metadata reduces scanning

For each column in each micro-partition, Snowflake records metadata such as:

- the minimum and maximum values;
- the number of distinct values; and
- other properties used for optimization and query processing.

The cloud-services layer uses this information for micro-partition pruning. If
a partition's value range cannot satisfy a filter, the warehouse does not scan
that partition. After pruning partitions, columnar storage also lets the
warehouse avoid reading columns that the query does not reference.

A simple, unfiltered `COUNT(*)` can be answered from maintained metadata rather
than by scanning all table data. Filters or row access policies can require a
data scan.

## Example: query one fiscal month

Assume Finance loads transactions throughout January and February. The initial
micro-partitions reflect load order, so late-arriving January transactions can
share a micro-partition with February transactions.

| Micro-partition | `transaction_date` range in metadata | February query |
| --- | --- | --- |
| `MP-1` | January 1 to January 20 | Pruned |
| `MP-2` | January 15 to February 5 | Scanned |
| `MP-3` | February 1 to February 28 | Scanned |

The overlapping ranges do not make the table incorrect. Snowflake consults the
metadata, skips `MP-1`, and scans only the required columns in `MP-2` and
`MP-3`.
