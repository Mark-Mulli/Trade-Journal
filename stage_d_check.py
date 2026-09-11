from config import DB_PATH
from database import connect, init_db


def main():
    conn = connect(DB_PATH)
    init_db(conn)

    cols = {r["name"] for r in conn.execute("PRAGMA table_info(trades)").fetchall()}
    required_cols = {
        "grade", "rule_violation", "rule_violation_type", "entry_thesis",
        "emotion", "primary_screenshot_path", "annotation_updated_at_msc",
    }
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    required_tables = {"trade_annotation_history", "trade_screenshots"}

    print(f"Database: {DB_PATH}")
    print("Stage D trade columns:", "PASS" if required_cols.issubset(cols) else "FAIL")
    print("Stage D tables:", "PASS" if required_tables.issubset(tables) else "FAIL")

    row = conn.execute(
        """
        SELECT position_id, symbol, status, strategy, setup, grade,
               rule_violation, emotion, primary_screenshot_path
        FROM trades ORDER BY entry_time_msc DESC LIMIT 1
        """
    ).fetchone()
    if row:
        print("\nLatest trade:")
        for key in row.keys():
            print(f"  {key}: {row[key]}")
    else:
        print("\nNo trades found yet.")

    revisions = conn.execute("SELECT COUNT(*) AS n FROM trade_annotation_history").fetchone()["n"]
    shots = conn.execute("SELECT COUNT(*) AS n FROM trade_screenshots").fetchone()["n"]
    print(f"\nAnnotation revisions: {revisions}")
    print(f"Screenshot records: {shots}")
    conn.close()


if __name__ == "__main__":
    main()
