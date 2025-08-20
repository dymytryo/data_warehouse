* Designed in academia
* Based on Apache Spark
* Designed for big data and machine learning - flexible for data scientis and engineers

It’s a data platform (built on top of Apache Spark) that provides:
* Storage layer → via Delta Lake (which is a transactional storage format, not a database).
* Compute engine → Spark, SQL, ML runtimes to process data.
* Governance & collaboration tools → Unity Catalog, MLflow, notebooks, jobs.

Core concepts: 
* `Lakehouse architecture` → Combines data lake + data warehouse (structured + unstructured in one place).
* `Delta Lake` → Transactional storage layer on top of Parquet with ACID guarantees, schema enforcement, and time travel.
* `Workspaces` → Shared environment for notebooks, jobs, repos, ML, and governance.

Compute: 
* Photon Engine -> Optimized execution engine for SQL & Delta Lake (massive speed-ups).

Streaming with Structured Streaming + Delta Live Tables (DLT).

Query Federation (query external DBs like MySQL, PostgreSQL, Snowflake).

Performance: 
* Use Delta Cache for frequent queries.
