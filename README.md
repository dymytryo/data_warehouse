# Data Systems Overview

## Portfolio case study

- [Snowflake acquisition data integration](snowflake/README.md): BILL and Divvy workload consolidation into Starburst/Trino and Apache Iceberg under Sarbanes-Oxley (SOX) controls.

---

## 👉 Key Difference
- **Database** = data stored + queried in the same system (e.g., Postgres, MySQL)
- **Specialized Database** = Non-relational like graph (Neptune) or Document (MongoDB)
- **Data Warehouse** = specialized database for analytics (e.g., Snowflake, Redshift)  
- **Query Engine** = queries data from external storage (e.g., Trino, DuckDB)  
- **Lakehouse Platform** = combines storage + query + governance + ML (e.g., Databricks)

---

## 🏛 Databases (RDBMS & OLTP)
Store data and provide SQL interface, usually row-oriented.
- `PostgreSQL`
- `MySQL`
- `Oracle Database`
- `Microsoft SQL Server`
- MariaDB
- Amazon Aurora (AWS’s managed relational DB, MySQL/Postgres compatible)
  
Other specialized DBs:
- Amazon Neptune → Graph database (property graph + RDF)
- MongoDB → Document DB
- Cassandra → Wide-column NoSQL DB
---

## 📦 Data Warehouses (Analytical DBs, OLAP)
Bundle **storage + compute**, optimized for analytics at scale.
- `Snowflake`
- `Amazon Redshift`
- `Google BigQuery`
- Azure Synapse Analytics
- `Teradata`

---

## 🔍 Query Engines
Don’t own storage, query external data (data lakes or federated sources).
- `Trino` (formerly PrestoSQL)
- `Starburst` (enterprise Trino)
- Apache Drill
- `AWS Athena` (Presto/Trino-based)
- Dremio
- DuckDB - embedded analytical query engine
---

## ⚡ Data Platforms / Lakehouse
Manage **compute, governance, and pipelines** on top of cloud object storage.
- Databricks (Lakehouse built on Spark + Delta Lake)
- Apache Spark
- Cloudera Data Platform (CDP)
- Google Dataplex

---
## Data Preparation / Analytics Tools

Alteryx → NOT a database, warehouse, or query engine.
Instead, it sits above these systems.
Pulls data from databases/warehouses/engines → transforms/cleans it → outputs to BI tools (Power BI, Tableau, Qlik) or back to storage.
Similar “layer” to Informatica, Talend, Dataiku, Trifacta (Wrangler), KNIME.
