# data_warehouse

Snowflake, Redshift = warehouses (storage + compute tightly integrated).

Trino/Starburst = query engines.

Spark SQL = SQL interface on Spark (engine).

Databricks = Lakehouse platform (not just an engine, not just a warehouse).

```mermaid
graph TD

subgraph Storage
  S3[S3 / ADLS / GCS]
  HDFS[HDFS]
  InternalDW[Warehouse Internal Storage]
end

subgraph Query_Engines
  Trino[Trino]
  Starburst["Starburst - Trino commercial"]
  SparkSQL["Spark SQL"]
end

subgraph Data_Warehouses
  Snowflake[Snowflake]
  Redshift["Amazon Redshift"]
end

subgraph Platforms
  Databricks[Databricks Lakehouse]
end

S3 --> Trino
ADLS --> Trino
GCS --> Trino
HDFS --> Trino

S3 --> Starburst
ADLS --> Starburst
GCS --> Starburst

S3 --> SparkSQL
ADLS --> SparkSQL
GCS --> SparkSQL

InternalDW --> Snowflake
InternalDW --> Redshift

S3 --> Databricks
ADLS --> Databricks
GCS --> Databricks
HDFS --> Databricks

Databricks --> SparkSQL
Databricks --> MLflow
Databricks --> DeltaLake[(Delta Lake Storage Layer)]
```
