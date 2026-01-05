import pendulum
from airflow.decorators import dag

from operators.edwh_container_operator import EdwhContainerOperator

@dag(
    dag_id="snowflake_statistics_collection",
    start_date=pendulum.datetime(2025, 7, 31, tz="UTC"),
    schedule="0 5 * * *",  # Example: Run daily at 5 AM UTC
    catchup=False,
    doc_md="""
    ### Snowflake Statistics Collection DAG

    This DAG runs the containerized snowflake statistics collection script using the
    custom EdwhContainerOperator. This is the standard, production-grade pattern
    for running tasks on ECS Fargate.

    The script within the container automatically detects its execution environment
    ('prod' when running in MWAA) and fetches the correct Starburst credentials
    from AWS Secrets Manager.
    """,
)
def snowflake_statistics_collection_dag():
    """Defines the statistics collection DAG."""

    collect_stats_task = EdwhContainerOperator(
        task_id="run_snowflake_stats_collection",
        command="python -m scripts.snowflake_stats_collection",
    )

# Instantiate the DAG to make it visible to Airflow
snowflake_statistics_collection_dag()
