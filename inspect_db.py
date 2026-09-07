import pandas as pd

from config import DB_PATH
from database import connect, init_db

conn = connect(DB_PATH)
init_db(conn)

print("\n" + "=" * 30 + " STAGE B TRADE SUMMARY " + "=" * 30)
summary = pd.read_sql_query(
    """
    SELECT
        position_id, symbol, direction, entry_datetime_local,
        entry_price, initial_sl, initial_tp, risk_amount,
        planned_rr, r_multiple, holding_minutes,
        entry_weekday, entry_session, outcome, net_pnl,
        risk_status, status
    FROM trades
    ORDER BY entry_time_msc DESC
    LIMIT 20
    """,
    conn,
)
print(summary.to_string(index=False))

for table in ["executions", "position_events", "account_snapshots"]:
    print("\n" + "=" * 30, table.upper(), "=" * 30)
    df = pd.read_sql_query(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT 20", conn)
    print(df.to_string(index=False))
conn.close()
