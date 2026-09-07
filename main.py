import time

import MetaTrader5 as mt5

from config import (
    ACCOUNT_SNAPSHOT_SECONDS,
    ANALYTICS_TIMEZONE,
    BACKFILL_DAYS,
    DB_PATH,
    EXPORT_DIR,
    EXPORT_SECONDS,
    OVERLAP_SECONDS,
    POLL_SECONDS,
    SESSION_TIMEZONE,
)
from database import connect, init_db
from journal import (
    account_mode_name,
    connect_mt5,
    export_csvs,
    rebuild_trades,
    snapshot_account,
    sync_deals,
    sync_positions_and_events,
)


def main():
    conn = connect(DB_PATH)
    init_db(conn)

    account = connect_mt5()
    account_login = int(account.login)
    mode = account_mode_name(int(account.margin_mode))

    print("=" * 70)
    print("MT5 TRADE JOURNAL - STAGE B - READ ONLY")
    print(f"Account:   {account_login}")
    print(f"Server:    {account.server}")
    print(f"Currency:  {account.currency}")
    print(f"Mode:      {mode}")
    print(f"Analytics: {ANALYTICS_TIMEZONE}")
    print(f"Sessions:  {SESSION_TIMEZONE}")
    print(f"DB:        {DB_PATH}")
    print("=" * 70)

    if mode != "RETAIL_HEDGING":
        print("WARNING: This version aggregates one MT5 position lifecycle per row.")
        print("Netting/reversal accounts need custom trade-idea splitting for perfect journaling.")

    last_snapshot = 0.0
    last_export = 0.0

    try:
        while True:
            try:
                account = mt5.account_info()
                if account is None:
                    raise RuntimeError(f"account_info failed: {mt5.last_error()}")

                new_deals = sync_deals(conn, account_login, BACKFILL_DAYS, OVERLAP_SECONDS)
                current_positions = sync_positions_and_events(conn, account_login)
                rebuild_trades(conn, account_login, current_positions.keys())

                now = time.time()
                if now - last_snapshot >= ACCOUNT_SNAPSHOT_SECONDS:
                    snapshot_account(conn, account)
                    last_snapshot = now

                if now - last_export >= EXPORT_SECONDS:
                    export_csvs(conn, account_login, EXPORT_DIR)
                    last_export = now

                if new_deals:
                    print(f"Captured {new_deals} new deal(s). Open positions: {len(current_positions)}")

            except Exception as exc:
                print(f"Cycle error: {exc}")
                mt5.shutdown()
                time.sleep(2)
                if not mt5.initialize():
                    print(f"Reconnect failed: {mt5.last_error()}")

            time.sleep(POLL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopping journal...")
    finally:
        try:
            export_csvs(conn, account_login, EXPORT_DIR)
        except Exception:
            pass
        conn.close()
        mt5.shutdown()
        print("Stopped cleanly.")


if __name__ == "__main__":
    main()
