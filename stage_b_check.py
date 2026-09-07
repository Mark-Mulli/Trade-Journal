"""Quick Stage B validation after main.py has run at least once."""
import sqlite3

from config import DB_PATH
from database import connect, init_db

REQUIRED = [
    "risk_amount", "planned_reward_amount", "planned_rr", "r_multiple",
    "holding_minutes", "entry_weekday", "entry_month", "entry_hour",
    "entry_session", "outcome", "risk_status",
]

conn = connect(DB_PATH)
init_db(conn)
columns = {row["name"] for row in conn.execute("PRAGMA table_info(trades)")}
missing = [c for c in REQUIRED if c not in columns]

print("Database:", DB_PATH)
print("Schema migration:", "PASS" if not missing else f"FAIL - missing {missing}")

count = conn.execute("SELECT COUNT(*) AS n FROM trades").fetchone()["n"]
print("Trades found:", count)

if count:
    row = conn.execute(
        """
        SELECT position_id, symbol, status, risk_amount, planned_rr,
               r_multiple, holding_minutes, entry_weekday,
               entry_session, outcome, risk_status
        FROM trades
        ORDER BY entry_time_msc DESC
        LIMIT 1
        """
    ).fetchone()
    print("Latest trade:")
    for key in row.keys():
        print(f"  {key}: {row[key]}")

conn.close()
