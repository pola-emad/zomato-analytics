import os
import numpy as np
import pandas as pd
import streamlit as st
import snowflake.connector
from openai import OpenAI
from dotenv import load_dotenv
from pathlib import Path
import time
import hashlib

EMBEDDING_MODEL = "nvidia/nemotron-3-embed-1b:free"
CHAT_MODEL = "minimax/minimax-m2.7:free"
NEW_REVIEWS = 50                # total sample size pulled from Snowflake
TOP_K = 5
CACHE_FILE = "review_embeddings.parquet"
EMBEDDING_BATCH_SIZE = 50
RATE_LIMIT_SLEEP_SECONDS = 1
MIN_SIMILARITY = 0.3


load_dotenv(Path.cwd() / ".env")
embed_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key= os.getenv("embedding_api_key")
)
chat_client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("api_key"),
)


def read_reviews_from_snowflake():
    conn = snowflake.connector.connect(
        account=os.getenv("SNOWFLAKE_ACCOUNT"),
        user=os.getenv("SNOWFLAKE_USER"),
        password=os.getenv("SNOWFLAKE_PASSWORD"),
        warehouse=os.getenv("SNOWFLAKE_WAREHOUSE"),
        database=os.getenv("SNOWFLAKE_DATABASE"),
        schema=os.getenv("SNOWFLAKE_SCHEMA"),
    )

    query = f"""
        SELECT 
    r.review_id,
    r.rating,
    r.comment,
    r.review_date,
    res.restaurant_name,
    res.city,
    res.cuisine
FROM ZOMATO.STAGING.STG__REVIEWS AS r SAMPLE ({NEW_REVIEWS} ROWS)
LEFT JOIN ZOMATO.STAGING.STG__RESTAURANTS AS res 
    ON r.restaurant_id = res.restaurant_id;
    """
    df = conn.cursor().execute(query).fetch_pandas_all()
    conn.close()

    df.columns = [col.lower() for col in df.columns]
    return df

def embed_reviews(df: pd.DataFrame, text_col: str, id_col: str,
                   cache_path: str = CACHE_FILE,
                   batch_size: int = EMBEDDING_BATCH_SIZE) -> pd.DataFrame:
    """
    Returns df with an added 'embedding' column.
    Uses a parquet cache so reviews already embedded are never re-sent to the API.
    """
    if os.path.exists(cache_path):
        cached = pd.read_parquet(cache_path)
        cached[id_col] = cached[id_col].astype(str)
        already_done = set(cached[id_col])
    else:
        cached = pd.DataFrame(columns=[id_col, "embedding"])
        already_done = set()

    df = df.copy()
    df[id_col] = df[id_col].astype(str)

    todo = df[~df[id_col].isin(already_done)]

    new_rows = []
    texts = todo[text_col].tolist()
    ids = todo[id_col].tolist()

    for i in range(0, len(texts), batch_size):
        batch_texts = texts[i:i + batch_size]
        batch_ids = ids[i:i + batch_size]

        response = embed_client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=batch_texts,
            encoding_format="float",
        )
        for id_, item in zip(batch_ids, response.data):
            new_rows.append({id_col: id_, "embedding": item.embedding})

        pd.concat([cached, pd.DataFrame(new_rows)]).to_parquet(cache_path)
        time.sleep(RATE_LIMIT_SLEEP_SECONDS)

    all_embeddings = pd.concat([cached, pd.DataFrame(new_rows)])
    return df.merge(all_embeddings, on=id_col, how="left")

def embed_query(query: str) -> list[float]:
    """
    Embeds a single user query for similarity search against cached review embeddings.
    No caching here — every query is (usually) different text.
    """
    response = embed_client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=query,
        encoding_format="float",
    )
    return response.data[0].embedding

def find_similar_reviews(query_embedding: list[float],
                          reviews_df: pd.DataFrame,
                          top_k: int = TOP_K) -> pd.DataFrame:
    """
    Returns the top_k most similar reviews to the query, ranked by cosine similarity.
    """
    query_vec = np.array(query_embedding)
    review_matrix = np.vstack(reviews_df["embedding"].values)

    # Defensive: normalize both sides even though the model claims to already do this.
    # Cost is negligible; protects against silent provider/version changes.
    query_norm = query_vec / np.linalg.norm(query_vec)
    review_norms = review_matrix / np.linalg.norm(review_matrix, axis=1, keepdims=True)

    similarities = review_norms @ query_norm  # (500,) vector of similarity scores

    top_indices = np.argsort(similarities)[::-1][:top_k]

    result = reviews_df.iloc[top_indices].copy()
    result["similarity_score"] = similarities[top_indices]
    return result

def get_cache_key(query: str, conversation_history: list[dict]) -> str:
    """
    Cache key must capture everything that affects the LLM's output —
    the same query text means different things with different prior context.
    """
    context_str = str(conversation_history) + query
    return hashlib.sha256(context_str.encode()).hexdigest()

def build_context(similar_reviews: pd.DataFrame, text_col: str,
                   min_similarity: float = MIN_SIMILARITY) -> str:
    """
    Filters retrieved reviews by a similarity threshold and formats them as
    plain text. The threshold decision happens here, in Python — the LLM
    never sees raw similarity scores.
    """
    relevant = similar_reviews[similar_reviews["similarity_score"] >= min_similarity]
    if relevant.empty:
        return ""
    return "\n\n".join(
        f"Restaurant: {row['restaurant_name']} | Cuisine: {row['cuisine']} | City: {row['city']}\nReview: {row[text_col]}"
        for _, row in relevant.iterrows()
    )

def ask_llm(query: str, similar_reviews: pd.DataFrame, text_col: str,
            conversation_history: list[dict]) -> str:
    """
    Answers a query using retrieved reviews as context, with session-level
    answer caching keyed on query + prior conversation.
    """
    SYSTEM_PROMPT = (
    "You are an assistant that answers questions about a food delivery app's "
    "customer reviews. Base your answers ONLY on the review excerpts provided "
    "in the context. If the context does not contain enough information to "
    "answer the question, say so explicitly instead of guessing or using "
    "outside knowledge."
)
    
    if "answer_cache" not in st.session_state:
        st.session_state.answer_cache = {}

    cache_key = get_cache_key(query, conversation_history)
    if cache_key in st.session_state.answer_cache:
        return st.session_state.answer_cache[cache_key]

    context_text = build_context(similar_reviews, text_col)

    if context_text:
        user_prompt = f"Context from customer reviews:\n{context_text}\n\nQuestion: {query}"
    else:
        user_prompt = f"No sufficiently relevant reviews were found. Question: {query}"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_history + [
    {"role": "user", "content": user_prompt}
]
    response = chat_client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
    )
    answer = response.choices[0].message.content

    st.session_state.answer_cache[cache_key] = answer
    return answer

st.title("Zomato Reviews — Chat with Customer Feedback")

# --- One-time setup, cached across reruns within the session ---
if "conversation_history" not in st.session_state:
    st.session_state.conversation_history = []

if "reviews_df" not in st.session_state:
    raw_df = read_reviews_from_snowflake()          # your existing function
    st.session_state.reviews_df = embed_reviews(raw_df, text_col="comment", id_col="review_id")

# --- Render prior turns ---
for msg in st.session_state.conversation_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# --- Handle new input ---
query = st.chat_input("Ask something about the reviews...")

if query:
    with st.chat_message("user"):
        st.markdown(query)

    query_embedding = embed_query(query)

    similar_reviews = find_similar_reviews(
        query_embedding,
        st.session_state.reviews_df,
        top_k=TOP_K,
    )

    answer = ask_llm(
        query=query,
        similar_reviews=similar_reviews,
        text_col="comment",
        conversation_history=st.session_state.conversation_history,
    )

    with st.chat_message("assistant"):
        st.markdown(answer)
        with st.expander("Retrieved reviews (debug view)"):
            st.dataframe(similar_reviews[["restaurant_name", "cuisine", "city", "comment", "similarity_score"]])

    st.session_state.conversation_history.append({"role": "user", "content": query})
    st.session_state.conversation_history.append({"role": "assistant", "content": answer})