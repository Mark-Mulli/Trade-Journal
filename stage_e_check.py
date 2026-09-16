from config import DB_PATH
from database import connect, init_db


def main():
    conn = connect(DB_PATH)
    init_db(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(trades)").fetchall()}
    required = {
        "mfe_price", "mae_price", "mfe_r", "mae_r", "capture_efficiency_pct",
        "giveback_r", "risk_used_pct", "planned_tp_touched", "initial_sl_touched",
        "excursion_tick_count", "excursion_status", "excursion_calculated_at_msc",
        "initial_sl_set_at_msc", "initial_tp_set_at_msc",
        "initial_sl_source", "initial_tp_source",
    }
    print(f"Database: {DB_PATH}")
    print("Stage E trade columns:", "PASS" if required.issubset(cols) else "FAIL")

    stats = conn.execute(
        """
        SELECT
          COUNT(*) AS trades,
          SUM(CASE WHEN status='CLOSED' THEN 1 ELSE 0 END) AS closed,
          SUM(CASE WHEN excursion_status='CALCULATED' THEN 1 ELSE 0 END) AS excursion_ok,
          SUM(CASE WHEN COALESCE(rule_violation,'NO')='YES' THEN 1 ELSE 0 END) AS violations
        FROM trades
        """
    ).fetchone()
    print(f"Trades: {stats['trades']} | Closed: {stats['closed']} | Excursion calculated: {stats['excursion_ok']} | Rule violations: {stats['violations']}")

    row = conn.execute(
        """
        SELECT position_id,symbol,status,initial_sl,initial_tp,
               initial_sl_set_at_msc,initial_tp_set_at_msc,
               initial_sl_source,initial_tp_source,risk_amount,planned_rr,
               r_multiple,mfe_r,mae_r,
               capture_efficiency_pct,giveback_r,risk_used_pct,
               planned_tp_touched,initial_sl_touched,excursion_status
        FROM trades
        ORDER BY entry_time_msc DESC LIMIT 1
        """
    ).fetchone()
    if row:
        print("\nLatest trade:")
        for key in row.keys():
            print(f"  {key}: {row[key]}")
    conn.close()


if __name__ == "__main__":
    main()
