import os
import gdown
import pandas as pd
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Step 2: Configure your Snowflake connection
# Credentials are loaded from .env file
conn = snowflake.connector.connect(
    user=os.getenv('SNOWFLAKE_USER'),
    password=os.getenv('SNOWFLAKE_PASSWORD'),
    account=os.getenv('SNOWFLAKE_ACCOUNT'),
    warehouse=os.getenv('SNOWFLAKE_WAREHOUSE'),
    database=os.getenv('SNOWFLAKE_DATABASE'),
    schema=os.getenv('SNOWFLAKE_SCHEMA')
)

# Step 3: Mapping of source table names, target tables, and Google Drive links
files_to_load = [
    {
        "source": "food",
        "target_table": "RAW_FOOD",
        "url": "https://drive.google.com/file/d/1hUIviZROYCcoRwy-IBHo4jsO3Yj-6VV7/view?usp=drive_link"
    },
    {
        "source": "menu",
        "target_table": "RAW_MENU",
        "url": "https://drive.google.com/file/d/1r79tEcSqcP8c25xYznDoVq-EjKDyO89b/view?usp=drive_link"
    },
    {
        "source": "order_items",
        "target_table": "RAW_ORDER_ITEMS",
        "url": "https://drive.google.com/file/d/1v0Vbxw8NoAWmp1xXvWbTfXPXpZdy9uam/view?usp=drive_link"
    },
    {
        "source": "orders",
        "target_table": "RAW_ORDERS",
        "url": "https://drive.google.com/file/d/1rXBEAzHQ6XdfEbgpMqOe6XLe9T5Uhbhz/view?usp=drive_link"
    },
    {
        "source": "restaurant",
        "target_table": "RAW_RESTAURANTS",
        "url": "https://drive.google.com/file/d/1Z-OkUWHKYD6-eC6YVQtlnDN57i4vtT6Y/view?usp=drive_link"
    },
    {
        "source": "reviews",
        "target_table": "RAW_REVIEWS",
        "url": "https://drive.google.com/file/d/1w0KD_zcNJyQeqZJpE0AuLjfwNdShNmkD/view?usp=drive_link"
    },
    {
        "source": "users",
        "target_table": "RAW_USERS",
        "url": "https://drive.google.com/file/d/1501bdqxQfSP4irKW4T1g-icLvPrc_FOt/view?usp=drive_link"
    }
]

# Step 4: Loop through each file, download directly in Google's cloud, and load to Snowflake
for item in files_to_load:
    source_name = item["source"]
    target_table = item["target_table"]
    url = item["url"]
    temp_file = f"{source_name}.csv"

    print(f"==================================================")
    print(f"Downloading '{source_name}' for target table '{target_table}'...")

    # Download file using gdown directly inside Colab container (uses 0 MB local bandwidth)
    gdown.download(url, temp_file, quiet=True, fuzzy=True)

    if os.path.exists(temp_file):
        # Read CSV into memory, disabling low_memory to better infer dtypes
        df = pd.read_csv(temp_file, low_memory=False)

        # Clean up column names (Snowflake best practice: uppercase columns)
        df.columns = [col.strip().upper() for col in df.columns]

        # Convert 'PRICE' column to numeric, coercing errors
        if 'PRICE' in df.columns:
            df['PRICE'] = pd.to_numeric(df['PRICE'], errors='coerce')

        print(f"Loading {len(df)} rows into Snowflake table '{target_table}'...")

        # Write pandas dataframe directly into Snowflake
        success, nchunks, nrows, _ = write_pandas(
            conn=conn,
            df=df,
            table_name=target_table,
            auto_create_table=True,  # Automatically creates table if it doesn't exist
            overwrite=False          # Set to True if you want to replace existing table data
        )

        print(f"SUCCESS: Loaded {nrows} rows into '{target_table}'.")

        # Delete local temp CSV to clear Colab memory
        os.remove(temp_file)
    else:
        print(f"ERROR: Failed to download file for {source_name}.")


# Step 5: Close Snowflake connection
conn.close()
print("\nAll target tables loaded successfully into Snowflake!")