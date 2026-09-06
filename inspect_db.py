import pandas as pd

from config import DB_PATH
from database import connect

conn = connect(DB_PATH)
for table in ["trades", "executions", "position_events", "account_snapshots"]:
    print("\n" + "=" * 30, table.upper(), "=" * 30)
    df = pd.read_sql_query(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT 20", conn)
    print(df.to_string(index=False))
conn.close()
