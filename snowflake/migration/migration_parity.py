import os
import re
import pandas as pd
from tqdm import tqdm
from trino.auth import BasicAuthentication
from trino.dbapi import connect

from common.utils import setup_logger
from ..utils.db_utils import TrinoTableWriter

logger = setup_logger()

# Database Connection Details from Environment Variables
DB_HOST = 'starburst.lakeprod.billdot.io'
DB_PORT = 8443
DB_USER = os.environ.get('ENT_PROD_USER')
DB_PASSWORD = os.environ.get('ENT_PROD_PASSWORD')

# Target Schema and Table Names for the Output
TARGET_SCHEMA = "bdc_redshift.elementary"
ROW_COMPARISON_TABLE = "snowflake_migration_row_comparison"
COL_COMPARISON_TABLE = "snowflake_migration_column_comparison"


# =============================================================================
# Data Comparison Logic
# =============================================================================

def perform_row_comparison(conn):
    """
    Performs row count comparison between Starburst and the new se_datalake tables.
    This version is optimized to find common tables first, then get counts.
    """
    logger.info("--- Starting Row Comparison ---")

    # 1. Fetch table lists from both sources with robust error handling
    try:
        logger.info("Fetching Starburst table list...")
        sb_tables = pd.read_sql("""
            SELECT table_schema, table_name
            FROM bdc_lakehouse.information_schema.tables
            WHERE table_schema LIKE 'se\\_%' ESCAPE '\\'
        """, conn)
        logger.debug(f"Found {len(sb_tables)} potential tables in Starburst.")
    except Exception as e:
        logger.error(f"Failed to fetch table list from Starburst (bdc_lakehouse). Error: {e}", exc_info=True)
        sb_tables = pd.DataFrame(columns=['table_schema', 'table_name'])

    try:
        logger.info("Fetching se_datalake table list...")
        # --- MODIFIED ---
        # Updated query to point to `se_datalake` and changed the schema filter.
        # Instead of looking for schemas starting with '_', we now exclude system schemas.
        # This assumes `se_datalake` primarily contains the schemas you want to compare.
        sf_tables = pd.read_sql("""
            SELECT table_schema, table_name
            FROM se_datalake.information_schema.tables
            WHERE table_schema != 'information_schema'
        """, conn)
        logger.debug(f"Found {len(sf_tables)} potential tables in se_datalake.")
    except Exception as e:
        # --- MODIFIED --- Updated log message for new source
        logger.error(f"Failed to fetch table list from se_datalake. Error: {e}", exc_info=True)
        sf_tables = pd.DataFrame(columns=['table_schema', 'table_name'])

    if sb_tables.empty or sf_tables.empty:
        logger.warning("One or both sources returned no tables. Aborting row comparison.")
        return pd.DataFrame()

    # 2. Normalize names for joining
    logger.debug("Normalizing schema and table names...")
    manual_map = {
        'se_ach': 'ach_wal_public',
        'se_authentication': 'authentication_public',
        'se_compliance': 'compliance_wal_public',
        'se_finance': 'finance',
        'se_fraud_compliance': 'fraud_compliance',
        'se_juno': 'juno_public',
        'se_machine_learning': 'machine_learning',
        'se_money_mover': 'money_mover_wal_public',
        'se_onboarding': 'onboarding_public',
        'se_other': 'other',
        'se_pendo': 'pendo_rep',
        'se_rewards': 'rewards_public',
        'se_risk': 'risk',
        'se_underwriting': 'underwriting_public',
        'se_viking_public': 'viking_public'
    }
    sb_tables['join_domain'] = sb_tables['table_schema'].apply(
        lambda s: manual_map.get(s, s[3:] if s.startswith('se_') else s))
    sb_tables['table_norm'] = sb_tables['table_name'].str.strip().str.lower()

    # --- NO CHANGE NEEDED HERE ---
    # The existing logic `s[1:] if s.startswith('_') else s` correctly handles
    # the old schemas with a prefix and the new schemas without one.
    sf_tables['join_domain'] = sf_tables['table_schema'].apply(
        lambda s: manual_map.get(s, s[1:] if s.startswith('_') else s))
    sf_tables['table_norm'] = sf_tables['table_name'].str.strip().str.lower()

    # 3. Find the intersection of tables *before* getting counts
    logger.debug("Finding common tables between sources...")
    common_tables_df = pd.merge(
        sb_tables, sf_tables,
        on=['join_domain', 'table_norm'],
        suffixes=('_sb', '_sf')
    )
    logger.info(f"Found {len(common_tables_df)} common tables to compare.")
    logger.debug(f"Common tables head:\n{common_tables_df.head().to_string()}")

    # 4. Loop through the *common* tables to get counts
    counts = []
    for _, row in tqdm(common_tables_df.iterrows(), total=common_tables_df.shape[0], desc="Getting Row Counts"):
        try:
            # Get Starburst count
            sb_query = f"SELECT COUNT(*) as row_count FROM bdc_lakehouse.\"{row['table_schema_sb']}\".\"{row['table_name_sb']}\""
            sb_count = pd.read_sql(sb_query, conn)['row_count'][0]

            # --- MODIFIED ---
            # Get count from the new `se_datalake` source
            sf_query = f"SELECT COUNT(*) as row_count FROM se_datalake.\"{row['table_schema_sf']}\".\"{row['table_name_sf']}\""
            sf_count = pd.read_sql(sf_query, conn)['row_count'][0]

            counts.append({
                'schema_sb': row['table_schema_sb'], 'table_name': row['table_name_sb'],
                'schema_sf': row['table_schema_sf'],
                'starburst_row_count': int(sb_count), 'snowflake_row_count': int(sf_count)
            })
        except Exception as e:
            logger.warning(f"Could not get counts for table {row['table_name_sb']}, skipping. Error: {e}")

    if not counts:
        logger.warning("Could not retrieve counts for any common tables.")
        return pd.DataFrame()

    # 5. Calculate differences
    counts_df = pd.DataFrame(counts)
    counts_df['row_count_diff'] = counts_df['starburst_row_count'] - counts_df['snowflake_row_count']
    counts_df['row_count_pct_diff'] = (
            counts_df['row_count_diff'] / counts_df[['starburst_row_count', 'snowflake_row_count']].max(axis=1)
    ).round(3)

    final_df = counts_df[
        ['schema_sf', 'schema_sb', 'table_name', 'starburst_row_count', 'snowflake_row_count', 'row_count_diff',
         'row_count_pct_diff']]
    logger.debug(f"Final row comparison result head:\n{final_df.head().to_string()}")
    logger.info("--- Row Comparison Finished ---\n")
    return final_df.reset_index(drop=True)


def perform_column_comparison(conn, mapping_df):
    """
    Performs column and data type comparison with enhanced data presence checking.
    This version is optimized to only query columns for the common tables
    found in the row comparison step, and includes data presence validation
    for columns missing in Starburst.
    """
    logger.info("--- Starting Enhanced Column Comparison ---")
    if mapping_df.empty:
        logger.warning("Mapping DataFrame is empty, skipping column comparison.")
        return pd.DataFrame()

    all_comparisons = []
    for _, row in tqdm(mapping_df.iterrows(), total=mapping_df.shape[0], desc="Comparing Columns"):
        try:
            # Fetch columns for the specific Starburst table
            sb_schema = row['schema_sb']
            table_name = row['table_name']
            sb_query = f"SELECT column_name, data_type FROM bdc_lakehouse.information_schema.columns WHERE table_schema = '{sb_schema}' AND table_name = '{table_name}'"
            sb_cols = pd.read_sql(sb_query, conn)

            # Fetch columns from the se_datalake source
            sf_schema = row['schema_sf']
            sf_query = f"SELECT column_name, data_type FROM se_datalake.information_schema.columns WHERE table_schema = '{sf_schema}' AND table_name = '{table_name}'"
            sf_cols = pd.read_sql(sf_query, conn)

            logger.debug(
                f"Found {len(sb_cols)} columns in Starburst and {len(sf_cols)} in se_datalake for table '{table_name}'")

            # Merge results for this one table
            merged = pd.merge(
                sb_cols.rename(columns={'column_name': 'column_name_sb', 'data_type': 'data_type_sb'}),
                sf_cols.rename(columns={'column_name': 'column_name_sf', 'data_type': 'data_type_sf'}),
                left_on='column_name_sb', right_on='column_name_sf', how='outer'
            )
            merged['table_schema_sb'] = sb_schema
            merged['table_schema_sf'] = sf_schema
            merged['table_name'] = table_name

            # Initialize data presence columns
            merged['sf_non_null_count'] = None
            merged['sf_total_rows'] = None
            merged['sf_non_null_percentage'] = None
            merged['sf_has_data'] = None
            merged['data_loss_risk'] = None

            # Check data presence for columns missing in Starburst
            missing_in_sb_mask = pd.isnull(merged['column_name_sb'])
            missing_in_sb = merged[missing_in_sb_mask]

            if not missing_in_sb.empty:
                logger.debug(
                    f"Checking data presence for {len(missing_in_sb)} columns missing in Starburst for table {table_name}")

                for idx, missing_col in missing_in_sb.iterrows():
                    col_name = missing_col['column_name_sf']

                    # Skip known system columns
                    if col_name in ['dl_deleted_ts', 'dl_load_ts', '_fivetran_deleted', '_fivetran_synced']:
                        continue

                    try:
                        # Check data presence in se_datalake for this missing column
                        data_check_query = f'''
                        SELECT 
                            COUNT("{col_name}") as non_null_count,
                            COUNT(*) as total_rows
                        FROM se_datalake."{sf_schema}"."{table_name}"
                        '''

                        data_result = pd.read_sql(data_check_query, conn)
                        non_null_count = int(data_result['non_null_count'].iloc[0])
                        total_rows = int(data_result['total_rows'].iloc[0])
                        non_null_pct = round((non_null_count / total_rows * 100), 2) if total_rows > 0 else 0
                        has_data = non_null_count > 0

                        # Determine risk level
                        if has_data:
                            if non_null_pct >= 50:
                                risk = 'HIGH'
                            elif non_null_pct >= 10:
                                risk = 'MEDIUM'
                            else:
                                risk = 'LOW'
                        else:
                            risk = 'NONE'

                        # Update the merged dataframe
                        merged.loc[idx, 'sf_non_null_count'] = non_null_count
                        merged.loc[idx, 'sf_total_rows'] = total_rows
                        merged.loc[idx, 'sf_non_null_percentage'] = non_null_pct
                        merged.loc[idx, 'sf_has_data'] = has_data
                        merged.loc[idx, 'data_loss_risk'] = risk

                        if has_data:
                            logger.info(
                                f"Column {table_name}.{col_name}: {non_null_count}/{total_rows} ({non_null_pct}%) - {risk} RISK")

                    except Exception as e:
                        logger.warning(f"Could not check data presence for {table_name}.{col_name}: {e}")
                        merged.loc[idx, 'sf_non_null_count'] = -1  # Indicates error
                        merged.loc[idx, 'sf_total_rows'] = -1
                        merged.loc[idx, 'sf_non_null_percentage'] = -1
                        merged.loc[idx, 'sf_has_data'] = None
                        merged.loc[idx, 'data_loss_risk'] = 'ERROR'

            all_comparisons.append(merged)

        except Exception as e:
            logger.warning(f"Could not compare columns for table '{row['table_name']}', skipping. Error: {e}")

    if not all_comparisons:
        logger.warning("No column information was gathered to compare.")
        return pd.DataFrame()

    comparison_df = pd.concat(all_comparisons, ignore_index=True)

    # Normalize data types
    def normalize_dtype(dtype):
        if pd.isnull(dtype): return None
        dtype = dtype.lower().strip()
        # Normalize all timestamp variations to just 'timestamp'
        if 'timestamp' in dtype:
            return 'timestamp'
        # Normalize varchar(N) to varchar
        dtype = re.sub(r'varchar\(\d+\)', 'varchar', dtype)
        # Normalize decimal(P, S) to decimal
        dtype = re.sub(r'decimal\([\d, ]+\)', 'decimal', dtype)
        return dtype

    comparison_df['data_type_sb'] = comparison_df['data_type_sb'].apply(normalize_dtype)
    comparison_df['data_type_sf'] = comparison_df['data_type_sf'].apply(normalize_dtype)

    # Determine status
    def get_status(row):
        if pd.isnull(row['data_type_sb']): return 'Missing in Starburst'
        if pd.isnull(row['data_type_sf']): return 'Missing in Snowflake'
        return 'Match' if row['data_type_sb'] == row['data_type_sf'] else 'Type Mismatch'

    comparison_df['data_type_status'] = comparison_df.apply(get_status, axis=1)

    # Exclude known system columns
    cols_to_exclude = ['dl_deleted_ts', 'dl_load_ts', '_fivetran_deleted', '_fivetran_synced']
    comparison_df = comparison_df[
        ~(comparison_df['column_name_sb'].isin(cols_to_exclude) |
          comparison_df['column_name_sf'].isin(cols_to_exclude))
    ]

    # Log summary of data loss risks
    high_risk = comparison_df[comparison_df['data_loss_risk'] == 'HIGH']
    medium_risk = comparison_df[comparison_df['data_loss_risk'] == 'MEDIUM']

    if not high_risk.empty:
        logger.warning(f"HIGH RISK: {len(high_risk)} columns missing in Starburst with significant data")
    if not medium_risk.empty:
        logger.warning(f"MEDIUM RISK: {len(medium_risk)} columns missing in Starburst with moderate data")

    logger.info("--- Enhanced Column Comparison Finished ---")
    return comparison_df


# =============================================================================
# Main Execution
# =============================================================================

def main():
    """
    Main function to run the QA script with enhanced column comparison.
    """
    # --- Setup logger ---
    logger = setup_logger()

    # --- Verify Credentials ---
    if not all([DB_USER, DB_PASSWORD]):
        logger.critical("Missing database credentials. Ensure ENT_PROD_USER and ENT_PROD_PASSWORD are set.")
        return

    conn = None
    try:
        # --- Connect to Database ---
        logger.info(f"Connecting to database at {DB_HOST}:{DB_PORT} as user '{DB_USER}'...")
        conn = connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            auth=BasicAuthentication(DB_USER, DB_PASSWORD),
            http_scheme='https',
            request_timeout=120
        )
        logger.info("Connection successful.")

        # --- Initialize Writer ---
        writer = TrinoTableWriter(conn)

        # --- Perform Row Comparison and Write Results ---
        row_comparison_df = perform_row_comparison(conn)
        if not row_comparison_df.empty:
            logger.info("Row Comparison Results (first 5 rows):\n%s", row_comparison_df.head().to_string())
            writer.write_dataframe(row_comparison_df, ROW_COMPARISON_TABLE, TARGET_SCHEMA, chunksize=500)

            # --- Perform Enhanced Column Comparison and Write Results ---
            mapping_for_cols = row_comparison_df[['schema_sf', 'schema_sb', 'table_name']].copy()
            column_comparison_df = perform_column_comparison(conn, mapping_for_cols)

            if not column_comparison_df.empty:
                non_matches_df = column_comparison_df[column_comparison_df['data_type_status'] != 'Match']
                logger.info("Column Comparison Non-Match Results (first 5 rows):\n%s",
                            non_matches_df.head().to_string())

                # Log summary of data loss risks
                high_risk_cols = column_comparison_df[column_comparison_df['data_loss_risk'] == 'HIGH']
                medium_risk_cols = column_comparison_df[column_comparison_df['data_loss_risk'] == 'MEDIUM']

                if not high_risk_cols.empty:
                    logger.critical(f"CRITICAL: {len(high_risk_cols)} HIGH RISK columns found!")
                    for _, col in high_risk_cols.iterrows():
                        logger.critical(
                            f"   {col['table_name']}.{col['column_name_sf']}: {col['sf_non_null_count']} values ({col['sf_non_null_percentage']}%)")

                if not medium_risk_cols.empty:
                    logger.warning(f"WARNING: {len(medium_risk_cols)} MEDIUM RISK columns found!")
                    for _, col in medium_risk_cols.iterrows():
                        logger.warning(
                            f"   {col['table_name']}.{col['column_name_sf']}: {col['sf_non_null_count']} values ({col['sf_non_null_percentage']}%)")

                # Convert enhancement column data types to avoid schema mismatch
                logger.info("Converting enhancement column data types for table compatibility...")
                column_comparison_df['sf_non_null_count'] = column_comparison_df['sf_non_null_count'].astype(str)
                column_comparison_df['sf_total_rows'] = column_comparison_df['sf_total_rows'].astype(str)
                column_comparison_df['sf_non_null_percentage'] = column_comparison_df['sf_non_null_percentage'].astype(str)
                column_comparison_df['sf_has_data'] = column_comparison_df['sf_has_data'].astype(str)

                writer.write_dataframe(column_comparison_df, COL_COMPARISON_TABLE, TARGET_SCHEMA, chunksize=500)
        else:
            logger.warning(
                "Row comparison did not produce any results to compare. Skipping column comparison and table writing.")

    except Exception as e:
        logger.critical("A critical error occurred during the main execution.", exc_info=True)
    finally:
        # --- Cleanup ---
        if conn:
            if 'writer' in locals() and writer:
                writer.close()
            conn.close()
            logger.info("Database connection closed.")


if __name__ == "__main__":
    main()
