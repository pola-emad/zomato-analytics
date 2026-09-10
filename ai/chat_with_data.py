import os
import numpy as np
import pandas as pd
import streamlit as st
import snowflake.connector
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import json

SCHEMA = """
Tables available (Snowflake). Use bare table names, no database or schema prefix.

DIM_CUSTOMER (CUSTOMER_ID,
CUSTOMER_NAME,
EMAIL,
AGE,
AGE_SEGMENT,
GENDER,
MARITAL_STATUS,
OCCUPATION,
INCOME_BAND,
EDUCATION,
FAMILY_SIZE)

DIM_FOOD(FOOD_ID,
FOOD_NAME,
VEG_OR_NON_VEG)

DIM_RESTAURANTS(FOOD_ID,
FOOD_NAME,
VEG_OR_NON_VEG)

FACT_ORDER_ITEMS(ORDER_ITEM_ID,
ORDER_ID,
RESTAURANT_ID,
FOOD_ID,
ORDER_TS,
ORDER_DATE,
CITY,
PRICE,
QUANTITY,
LINE_AMOUNT)

FACT_ORDERS(ORDER_ITEM_ID,
ORDER_ID,
RESTAURANT_ID,
FOOD_ID,
ORDER_TS,
ORDER_DATE,
CITY,
PRICE,
QUANTITY,
LINE_AMOUNT)

MART_DAILY_CITY_REVENUE(ORDER_DATE,
CITY,
ORDERS,
DELIVERED_ORDERS,
CANCEL_RATE,
GMV,
AOV)

MART_DELIVERY_SLA(CITY,
ORDER_HOUR,
DELIVERED_ORDERS,
P50,
P90)

MART_RESTAURANT_PERFORMANCE(RESTAURANT_ID,
RESTAURANT_NAME,
CITY,
CUISINE,
ORDERS,
REVENUE,
AVG_CUSTOMER_RATING,
AVG_DELIVERY_MIN)

Note: gmv means delivered revenue. Prefer the MART_ tables when they fit the question.
"""

FORBIDDEN_WORDS = ['drop', 'delete', 'truncate', 'alter', 'update', 'insert', 'create', 'replace', 'grant', 'revoke']

EXAMPLE_QUESTIONS = [
    "Top 10 cities by GMV",
    "Which cuisin has the most orders?",
    "Average delivery time by city, worst first",
    "Cancel rate by payment method"
]

SYSTEM_PROMPT = f"""
You are a Snowflake SQL expert. Write ONE SELECT query that answers the question.
 
Rules:
- SELECT queries only, never modify data.
- Use bare table names (FCT_ORDERS, not ZOMATO.MARTS.FCT_ORDERS).
- Add a LIMIT of 100 or less, unless the question asks for a single total.
- Reply as JSON in this exact format: {{"sql": "your query here"}}
- If the question is ambiguous, ask for clarification instead of guessing.
- if the query has an aggregation, or a numerical result, determine the suitable chart type and add it to the JSON reply "suitable_chart": "chart type" where chart type is one of: bar, line, pie.
{SCHEMA}
"""

# Load the .env file located beside this notebook.
load_dotenv(Path.cwd() / ".env")
MODEL ="nvidia/nemotron-3.5-lightning:free"
# Initialize the client pointing to OpenRouter's endpoint
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("api_key"),
)

def get_connection():
    return snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema="MARTS",
        role = "DBT_ROLE"
    )

def generate_sql_and_chart_type(question, conversation_history=None, system_prompt=SYSTEM_PROMPT):
    conversation_history = conversation_history or []
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            *conversation_history,
            {"role": "user", "content": question}
        ]
    )
    answer = response.choices[0].message.content
    return answer.replace("```json", "").replace("```", "").strip()


generate_sql_chart_type = generate_sql_and_chart_type


def parse_sql_response(response_text):
    try:
        response = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ValueError("The SQL assistant returned invalid JSON.") from exc

    sql = response.get("sql")
    chart_type = response.get("suitable_chart", "")
    if not isinstance(sql, str) or not sql.strip():
        raise ValueError("The SQL assistant did not return a query.")
    if chart_type not in {"bar", "line", "pie", ""}:
        chart_type = ""
    return {"sql": sql.strip(), "suitable_chart": chart_type}

def is_safe(sql):
    lowered = sql.lower()

    if not lowered.startswith("select") and not lowered.startswith("with"):
        return False

    for word in FORBIDDEN_WORDS:
        if word in lowered:
            return False

    return True


def run_query(sql):
    conn = get_connection()
    try:
        return conn.cursor().execute(sql).fetch_pandas_all()
    finally:
        conn.close()


def visualize_results(results_df, chart_type):
    if results_df.empty or not chart_type:
        return

    if len(results_df.columns) < 2:
        return

    label_column = results_df.columns[0]
    numeric_columns = results_df.select_dtypes(include="number").columns.tolist()
    if not numeric_columns:
        return

    chart_df = results_df.set_index(label_column)[numeric_columns]
    if chart_type == "bar":
        st.bar_chart(chart_df)
    elif chart_type == "line":
        st.line_chart(chart_df)
    elif chart_type == "pie":
        pie_column = numeric_columns[0]
        pie_data = results_df[[label_column, pie_column]].rename(
            columns={label_column: "label", pie_column: "value"}
        )
        st.vega_lite_chart(
            pie_data,
            {
                "mark": {"type": "arc", "tooltip": True},
                "encoding": {
                    "theta": {"field": "value", "type": "quantitative"},
                    "color": {"field": "label", "type": "nominal"},
                },
            },
            use_container_width=True,
        )


def result_context(sql, chart_type, results_df):
    if results_df.empty:
        result_text = "The query returned no rows."
    else:
        result_text = results_df.head(20).to_string(index=False)
    return (
        f"SQL: {sql}\n"
        f"Visualization: {chart_type or 'none'}\n"
        f"Query result (first 20 rows):\n{result_text}"
    )


def main():
    st.title("Chat with your Zomato Data")
    st.caption(f"Ask in English, {MODEL} writes the SQL, Snowflake runs it")

    with st.sidebar:
        st.header("Example Questions")
        for example in EXAMPLE_QUESTIONS:
            st.markdown(f"- {example}")
        if st.button("Clear conversation"):
            st.session_state.messages = []
            st.rerun()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant" and message.get("result") is not None:
                st.dataframe(message["result"], use_container_width=True)
                visualize_results(message["result"], message.get("chart_type", ""))
                with st.expander("SQL"):
                    st.code(message["sql"], language="sql")

    question = st.chat_input("Ask something about your Zomato data...")
    if not question:
        return

    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    conversation_history = [
        {
            "role": message["role"],
            "content": message.get("context", message["content"]),
        }
        for message in st.session_state.messages[:-1]
    ]

    with st.chat_message("assistant"):
        try:
            with st.spinner("Generating SQL and running the query..."):
                response_text = generate_sql_chart_type(
                    question, conversation_history=conversation_history
                )
                response = parse_sql_response(response_text)
                if not is_safe(response["sql"]):
                    raise ValueError("Only read-only SELECT queries are allowed.")
                results_df = run_query(response["sql"])

            st.dataframe(results_df, use_container_width=True)
            visualize_results(results_df, response["suitable_chart"])
            with st.expander("SQL"):
                st.code(response["sql"], language="sql")

            assistant_context = result_context(
                response["sql"], response["suitable_chart"], results_df
            )
            st.session_state.messages.append({
                "role": "assistant",
                "content": "Here are the query results.",
                "result": results_df,
                "sql": response["sql"],
                "chart_type": response["suitable_chart"],
                "context": assistant_context,
            })
        except (ValueError, json.JSONDecodeError, snowflake.connector.Error) as exc:
            error_message = f"I couldn't complete that request: {exc}"
            st.error(error_message)
            st.session_state.messages.append({"role": "assistant", "content": error_message})


if __name__ == "__main__":
    main()
