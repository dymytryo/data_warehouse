#!/usr/bin/env python3
"""Compare migrated tables exposed through a Trino-compatible query layer.

Configuration is supplied through environment variables. The script
writes row- and column-level evidence to CSV files and does not modify either
data platform.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from trino.auth import BasicAuthentication
from trino.dbapi import connect


LOGGER = logging.getLogger("migration_parity")
SYSTEM_COLUMNS = {
    "_deleted_timestamp",
    "_fivetran_deleted",
    "_fivetran_synced",
    "_load_timestamp",
}


@dataclass(frozen=True)
class Config:
    host: str
    port: int
    user: str
    password: str
    source_catalog: str
    target_catalog: str
    schema_map: dict[str, str]
    output_dir: Path

    @classmethod
    def from_environment(cls) -> "Config":
        required = {
            "TRINO_HOST": os.getenv("TRINO_HOST"),
            "TRINO_USER": os.getenv("TRINO_USER"),
            "TRINO_PASSWORD": os.getenv("TRINO_PASSWORD"),
            "SOURCE_CATALOG": os.getenv("SOURCE_CATALOG"),
            "TARGET_CATALOG": os.getenv("TARGET_CATALOG"),
            "MIGRATION_SCHEMA_MAP": os.getenv("MIGRATION_SCHEMA_MAP"),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                "Missing required environment variables: " + ", ".join(missing)
            )

        try:
            schema_map = json.loads(required["MIGRATION_SCHEMA_MAP"] or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("MIGRATION_SCHEMA_MAP must be valid JSON") from exc

        if not isinstance(schema_map, dict) or not schema_map:
            raise ValueError(
                "MIGRATION_SCHEMA_MAP must map source schemas to target schemas"
            )
        if not all(
            isinstance(source, str) and isinstance(target, str)
            for source, target in schema_map.items()
        ):
            raise ValueError("Every schema-map key and value must be a string")

        return cls(
            host=required["TRINO_HOST"] or "",
            port=int(os.getenv("TRINO_PORT", "8443")),
            user=required["TRINO_USER"] or "",
            password=required["TRINO_PASSWORD"] or "",
            source_catalog=required["SOURCE_CATALOG"] or "",
            target_catalog=required["TARGET_CATALOG"] or "",
            schema_map=schema_map,
            output_dir=Path(os.getenv("MIGRATION_OUTPUT_DIR", "artifacts")),
        )


def quote_identifier(value: str) -> str:
    """Quote a Trino identifier after escaping embedded double quotes."""
    return '"' + value.replace('"', '""') + '"'


def sql_literal(value: str) -> str:
    """Quote a SQL string literal after escaping embedded single quotes."""
    return "'" + value.replace("'", "''") + "'"


def relation(catalog: str, schema: str, table: str) -> str:
    return ".".join(quote_identifier(part) for part in (catalog, schema, table))


def query_dataframe(connection: Any, query: str) -> pd.DataFrame:
    return pd.read_sql_query(query, connection)


def inventory(
    connection: Any,
    catalog: str,
    schemas: list[str],
) -> pd.DataFrame:
    schema_list = ", ".join(sql_literal(schema) for schema in schemas)
    query = f"""
        SELECT table_schema, table_name, table_type
        FROM {quote_identifier(catalog)}.information_schema.tables
        WHERE table_schema IN ({schema_list})
          AND table_type IN ('BASE TABLE', 'VIEW', 'MATERIALIZED VIEW')
    """
    return query_dataframe(connection, query)


def build_table_map(connection: Any, config: Config) -> pd.DataFrame:
    source = inventory(
        connection,
        config.source_catalog,
        list(config.schema_map),
    ).rename(
        columns={
            "table_schema": "source_schema",
            "table_name": "source_table",
            "table_type": "source_type",
        }
    )
    target = inventory(
        connection,
        config.target_catalog,
        sorted(set(config.schema_map.values())),
    ).rename(
        columns={
            "table_schema": "target_schema",
            "table_name": "target_table",
            "table_type": "target_type",
        }
    )

    source["target_schema"] = source["source_schema"].map(config.schema_map)
    source["table_key"] = source["source_table"].str.strip().str.lower()
    target["table_key"] = target["target_table"].str.strip().str.lower()

    return source.merge(
        target,
        on=["target_schema", "table_key"],
        how="left",
        validate="many_to_one",
    )


def fetch_count(
    connection: Any,
    catalog: str,
    schema: str,
    table: str,
) -> int:
    query = f"SELECT COUNT(*) AS row_count FROM {relation(catalog, schema, table)}"
    return int(query_dataframe(connection, query).iloc[0]["row_count"])


def compare_rows(
    connection: Any,
    config: Config,
    table_map: pd.DataFrame,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for mapping in table_map.itertuples(index=False):
        if pd.isna(mapping.target_table):
            rows.append(
                {
                    "source_schema": mapping.source_schema,
                    "target_schema": mapping.target_schema,
                    "table_name": mapping.source_table,
                    "source_row_count": None,
                    "target_row_count": None,
                    "row_count_difference": None,
                    "row_count_percent_difference": None,
                    "status": "missing_target",
                }
            )
            continue

        try:
            source_count = fetch_count(
                connection,
                config.source_catalog,
                mapping.source_schema,
                mapping.source_table,
            )
            target_count = fetch_count(
                connection,
                config.target_catalog,
                mapping.target_schema,
                mapping.target_table,
            )
            difference = target_count - source_count
            denominator = max(source_count, target_count, 1)
            percent_difference = round(difference / denominator, 6)
            status = "match" if difference == 0 else "different"
        except Exception as exc:  # one inaccessible table should not stop the run
            LOGGER.warning("Count failed for %s: %s", mapping.source_table, exc)
            source_count = target_count = difference = percent_difference = None
            status = "query_error"

        rows.append(
            {
                "source_schema": mapping.source_schema,
                "target_schema": mapping.target_schema,
                "table_name": mapping.source_table,
                "source_row_count": source_count,
                "target_row_count": target_count,
                "row_count_difference": difference,
                "row_count_percent_difference": percent_difference,
                "status": status,
            }
        )

    return pd.DataFrame(rows)


def fetch_columns(
    connection: Any,
    catalog: str,
    schema: str,
    table: str,
) -> pd.DataFrame:
    query = f"""
        SELECT column_name, data_type
        FROM {quote_identifier(catalog)}.information_schema.columns
        WHERE table_schema = {sql_literal(schema)}
          AND table_name = {sql_literal(table)}
    """
    return query_dataframe(connection, query)


def normalize_data_type(value: Any) -> str | None:
    if pd.isna(value):
        return None
    normalized = str(value).strip().lower()
    if "timestamp" in normalized:
        return "timestamp"
    normalized = re.sub(r"varchar\(\d+\)", "varchar", normalized)
    normalized = re.sub(r"decimal\([\d, ]+\)", "decimal", normalized)
    return normalized


def data_presence(
    connection: Any,
    config: Config,
    schema: str,
    table: str,
    column: str,
) -> tuple[int, int, float]:
    query = f"""
        SELECT
            COUNT({quote_identifier(column)}) AS non_null_count,
            COUNT(*) AS total_count
        FROM {relation(config.source_catalog, schema, table)}
    """
    result = query_dataframe(connection, query).iloc[0]
    non_null_count = int(result["non_null_count"])
    total_count = int(result["total_count"])
    non_null_percent = (
        round(non_null_count / total_count * 100, 2) if total_count else 0.0
    )
    return non_null_count, total_count, non_null_percent


def risk_level(non_null_percent: float) -> str:
    if non_null_percent >= 50:
        return "high"
    if non_null_percent >= 10:
        return "medium"
    if non_null_percent > 0:
        return "low"
    return "none"


def compare_columns(
    connection: Any,
    config: Config,
    table_map: pd.DataFrame,
) -> pd.DataFrame:
    comparisons: list[pd.DataFrame] = []
    available = table_map[table_map["target_table"].notna()]

    for mapping in available.itertuples(index=False):
        try:
            source = fetch_columns(
                connection,
                config.source_catalog,
                mapping.source_schema,
                mapping.source_table,
            ).rename(
                columns={
                    "column_name": "source_column",
                    "data_type": "source_data_type",
                }
            )
            target = fetch_columns(
                connection,
                config.target_catalog,
                mapping.target_schema,
                mapping.target_table,
            ).rename(
                columns={
                    "column_name": "target_column",
                    "data_type": "target_data_type",
                }
            )
        except Exception as exc:
            LOGGER.warning(
                "Column metadata check failed for %s: %s",
                mapping.source_table,
                exc,
            )
            comparisons.append(
                pd.DataFrame(
                    [
                        {
                            "source_schema": mapping.source_schema,
                            "target_schema": mapping.target_schema,
                            "table_name": mapping.source_table,
                            "source_column": None,
                            "target_column": None,
                            "source_data_type": None,
                            "target_data_type": None,
                            "status": "query_error",
                            "non_null_count": None,
                            "total_count": None,
                            "non_null_percent": None,
                            "data_loss_risk": "query_error",
                        }
                    ]
                )
            )
            continue

        source["column_key"] = source["source_column"].str.lower()
        target["column_key"] = target["target_column"].str.lower()
        merged = source.merge(target, on="column_key", how="outer")
        merged["source_schema"] = mapping.source_schema
        merged["target_schema"] = mapping.target_schema
        merged["table_name"] = mapping.source_table
        merged["source_data_type"] = merged["source_data_type"].map(
            normalize_data_type
        )
        merged["target_data_type"] = merged["target_data_type"].map(
            normalize_data_type
        )
        merged["non_null_count"] = None
        merged["total_count"] = None
        merged["non_null_percent"] = None
        merged["data_loss_risk"] = None

        for index, column in merged[merged["target_column"].isna()].iterrows():
            source_column = column["source_column"]
            if pd.isna(source_column) or str(source_column).lower() in SYSTEM_COLUMNS:
                continue
            try:
                non_null, total, percent = data_presence(
                    connection,
                    config,
                    mapping.source_schema,
                    mapping.source_table,
                    str(source_column),
                )
                merged.at[index, "non_null_count"] = non_null
                merged.at[index, "total_count"] = total
                merged.at[index, "non_null_percent"] = percent
                merged.at[index, "data_loss_risk"] = risk_level(percent)
            except Exception as exc:
                LOGGER.warning(
                    "Data-presence check failed for %s.%s: %s",
                    mapping.source_table,
                    source_column,
                    exc,
                )
                merged.at[index, "data_loss_risk"] = "query_error"

        def status(row: pd.Series) -> str:
            if pd.isna(row["target_column"]):
                return "missing_target"
            if pd.isna(row["source_column"]):
                return "target_only"
            if row["source_data_type"] != row["target_data_type"]:
                return "type_mismatch"
            return "match"

        merged["status"] = merged.apply(status, axis=1)
        comparisons.append(merged)

    if not comparisons:
        return pd.DataFrame()

    result = pd.concat(comparisons, ignore_index=True)
    return result[
        [
            "source_schema",
            "target_schema",
            "table_name",
            "source_column",
            "target_column",
            "source_data_type",
            "target_data_type",
            "status",
            "non_null_count",
            "total_count",
            "non_null_percent",
            "data_loss_risk",
        ]
    ]


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    config = Config.from_environment()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    connection = connect(
        host=config.host,
        port=config.port,
        user=config.user,
        auth=BasicAuthentication(config.user, config.password),
        http_scheme=os.getenv("TRINO_SCHEME", "https"),
        request_timeout=120,
    )

    try:
        table_map = build_table_map(connection, config)
        row_results = compare_rows(connection, config, table_map)
        row_results.to_csv(config.output_dir / "row_comparison.csv", index=False)

        column_results = compare_columns(connection, config, table_map)
        column_results.to_csv(
            config.output_dir / "column_comparison.csv",
            index=False,
        )
        LOGGER.info(
            "Compared %s source objects; evidence written to %s",
            len(table_map),
            config.output_dir,
        )
    finally:
        connection.close()


if __name__ == "__main__":
    main()
