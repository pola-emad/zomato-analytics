"""
Zomato Analytics Pipeline DAG

Orchestrates:
1. Loading data from Google Drive to Snowflake
2. Running dbt transformations
"""

from datetime import datetime, timedelta

from airflow.decorators import dag, task



# Default DAG arguments
default_args = {
    "owner": "analytics",
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
    "start_date": datetime(2026, 9, 5),
}


@dag(
    dag_id="zomato_load_and_transform",
    default_args=default_args,
    description="Load Zomato data from GDrive and run dbt transformations",
    schedule="@daily",
    catchup=False,
    tags=["zomato", "analytics"],
)
def zomato_pipeline():
    """Main DAG for Zomato data pipeline"""

    @task.bash(task_id="load_data_from_gdrive")
    def load_gdrive_data():
        """
        Load data from Google Drive to Snowflake.
        Executes the load_data_from_gdrive_to_snowflake.py script.
        """
        return "python /opt/airflow/Scripts/load_data_from_gdrive_to_snowflake.py"

    @task.bash(task_id="dbt_build")
    def run_dbt_build():
        """
        Run dbt build to transform data in Snowflake.
        """
        return """
        cd /opt/airflow/zomato && \
        dbt build --exclude tag:ai \
        --profiles-dir /opt/airflow/zomato \
        --project-dir /opt/airflow/zomato
        """

    @task.bash( task_id="enrich_reviews")
    def build_reviews_enriched():
        bash_command=f"python /opt/airflow/ai/reviews_enrichment.py"
        return bash_command

    @task.bash( task_id="build_ai_dbt_models")
    def build_ai_dbt_models():
        bash_command="""
        cd /opt/airflow/zomato && \
        dbt build --select tag:ai \
        --profiles-dir /opt/airflow/zomato \
        --project-dir /opt/airflow/zomato
        """
        return bash_command
    # Define task dependencies
    load_task = load_gdrive_data()
    dbt_task = run_dbt_build()
    enrich_review_task = build_reviews_enriched()
    build_ai_dbt_models_task = build_ai_dbt_models()

    # Execution order: load data first, then run dbt
    load_task >> dbt_task >> enrich_review_task >> build_ai_dbt_models_task


# Instantiate the DAG
zomato_pipeline_dag = zomato_pipeline()
