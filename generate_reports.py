import MetaTrader5 as mt5

from advanced_reports import generate_advanced_reports
from config import DB_PATH, EXPORT_DIR, MIN_SAMPLE_TRADES, ROLLING_WINDOW_TRADES
from database import connect, init_db
from journal import connect_mt5


def main():
    conn = connect(DB_PATH)
    init_db(conn)
    account = connect_mt5()
    login = int(account.login)
    generate_advanced_reports(
        conn, login, EXPORT_DIR,
        rolling_window=ROLLING_WINDOW_TRADES,
        min_sample=MIN_SAMPLE_TRADES,
    )
    conn.close()
    mt5.shutdown()
    print(f"Stage E reports written to: {EXPORT_DIR}")


if __name__ == "__main__":
    main()
