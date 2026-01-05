import pandas as pd
import os
from ..utils.db_utils import run_queries_in_parallel
from common.utils import setup_logger

from common.clients import StarburstClient

# Initialize the logger
logger = setup_logger(name="snowflake_stats_collector")

SQL_QUERY_PATH = os.path.join(os.path.dirname(__file__), "get_snowflake_tables.sql")

def collect_snowflake_statistics(max_workers=8, use_cache=False):
    """
    Fetches and collects statistics for Snowflake tables in parallel,
    auto-detecting the environment.

    Args:
        max_workers (int): The number of parallel threads.
        use_cache (bool): If True, enables result caching.
    """
    query_items = []
    try:
        with open(SQL_QUERY_PATH, 'r') as f:
            fetch_tables_query = f.read()

        # Use the detected environment to connect and fetch the table list
        with StarburstClient() as connector:
            logger.info(f"Fetching table list using query from '{SQL_QUERY_PATH}'...")
            tables_to_process = connector.execute(fetch_tables_query)
            logger.info(f"Found {len(tables_to_process)} tables to process.")

        for catalog, schema, table_name in tables_to_process:
            full_table_name = f'{catalog}.{schema}."{table_name}"'
            query_items.append({
                'full_table_name': full_table_name,
                'cache_key': f"collect_stats:{full_table_name}"
            })

    except Exception as e:
        logger.critical(f"Failed to fetch initial table list. Error: {e}", exc_info=True)
        return

    if not query_items:
        logger.info("No tables to process. Exiting.")
        return

    # 3. Define the function for a single table
    def collect_stats_for_table(item):
        # The worker function also uses the detected environment for its connection
        with StarburstClient() as connector:
            table_to_process = item['full_table_name']
            command = f"ALTER TABLE {table_to_process} EXECUTE collect_statistics"
            connector.execute(command)
            return pd.DataFrame([{'table': table_to_process, 'status': 'success'}])

    # 4. Run tasks in parallel
    results_dfs = run_queries_in_parallel(
        query_items,
        collect_stats_for_table,
        max_workers=max_workers,
        use_cache=use_cache
    )

    # 5. Log the final summary
    if results_dfs:
        final_df = pd.concat(results_dfs, ignore_index=True)
        logger.info("--- Parallel Statistics Collection Summary ---")
        logger.info(f"Total successful operations: {len(final_df)}")
    else:
        logger.warning("No results were generated or retrieved.")


if __name__ == "__main__":
    logger.info("Starting Snowflake statistics collection script.")
    collect_snowflake_statistics(use_cache=False)
    logger.info("Script finished.")
