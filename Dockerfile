FROM apache/airflow:3.1.6

RUN pip install --no-cache-dir \
    dbt-snowflake==1.8.0 \
    openai \
    pandas \
    gdown \
    python-dotenv \
    snowflake-connector-python