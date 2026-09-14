import argparse
import time

import MetaTrader5 as mt5

from config import DB_PATH, EXCURSION_TICK_CHUNK_HOURS
from database import connect, init_db
from excursions import calculate_tick_excursion, save_excursion
from journal import connect_mt5


def main():
    parser = argparse.ArgumentParser(description="Backfill MAE/MFE from MT5 tick history.")
    parser.add_argument("--days", type=int, default=30, help="Only closed trades entered within this many days. Default 30.")
    parser.add_argument("--limit", type=int, default=100, help="Maximum trades to process this run.")
    parser.add_argument("--recalculate", action="store_true", help="Recalculate trades that already have excursion metrics.")
    args = parser.parse_args()

    conn = connect(DB_PATH)
    init_db(conn)
    account = connect_mt5()
    login = int(account.login)
    cutoff = int((time.time() - max(0, args.days) * 86400) * 1000)

    where = ["account_login=?", "status='CLOSED'", "exit_time_msc IS NOT NULL", "entry_time_msc>=?"]
    params = [login, cutoff]
    if not args.recalculate:
        where.append("COALESCE(excursion_status,'')<>'CALCULATED'")
    rows = conn.execute(
        f"SELECT * FROM trades WHERE {' AND '.join(where)} ORDER BY exit_time_msc DESC LIMIT ?",
        params + [max(1, args.limit)],
    ).fetchall()

    print(f"Account: {login}")
    print(f"Trades selected: {len(rows)}")
    done = 0
    try:
        for trade in rows:
            pid = int(trade["position_id"])
            print(f"[{done+1}/{len(rows)}] {trade['symbol']} position {pid} ... ", end="", flush=True)
            metrics = calculate_tick_excursion(trade, chunk_hours=EXCURSION_TICK_CHUNK_HOURS)
            save_excursion(conn, login, pid, metrics)
            print(metrics["excursion_status"], f"ticks={metrics['excursion_tick_count']}")
            done += 1
    finally:
        conn.close()
        mt5.shutdown()
    print(f"Completed: {done}")


if __name__ == "__main__":
    main()
