from config import DB_PATH
from database import connect, init_db


def show(conn, title, query, limit=10):
    rows = conn.execute(query + f" LIMIT {int(limit)}").fetchall()
    print(f"\n=== {title} ===")
    if not rows:
        print("(no rows)")
        return
    print(" | ".join(rows[0].keys()))
    for r in rows:
        print(" | ".join(str(r[k]) for k in r.keys()))


def main():
    conn = connect(DB_PATH)
    init_db(conn)
    show(conn, "TRADES", "SELECT position_id,symbol,direction,status,net_pnl,r_multiple,mfe_r,mae_r,capture_efficiency_pct,giveback_r,risk_used_pct,strategy,setup,grade,rule_violation,emotion,excursion_status FROM trades ORDER BY entry_time_msc DESC")
    show(conn, "ANNOTATION HISTORY", "SELECT revision_id,position_id,saved_at_msc,strategy,setup,grade,rule_violation,emotion FROM trade_annotation_history ORDER BY saved_at_msc DESC")
    show(conn, "SCREENSHOTS", "SELECT screenshot_id,position_id,captured_at_msc,source,is_primary,file_path FROM trade_screenshots ORDER BY captured_at_msc DESC")
    show(conn, "EXECUTIONS", "SELECT deal_ticket,position_id,symbol,time_msc,volume,price,profit,commission,swap,fee FROM executions ORDER BY time_msc DESC")
    conn.close()


if __name__ == "__main__":
    main()
