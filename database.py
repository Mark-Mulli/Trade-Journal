import sqlite3
from pathlib import Path


STAGE_B_TRADE_COLUMNS = {
    "risk_amount": "REAL",
    "planned_reward_amount": "REAL",
    "planned_rr": "REAL",
    "r_multiple": "REAL",
    "risk_status": "TEXT",
    "risk_calculated_at_msc": "INTEGER",
    "risk_calc_context": "TEXT",
    "holding_seconds": "INTEGER",
    "holding_minutes": "REAL",
    "entry_datetime_local": "TEXT",
    "entry_date": "TEXT",
    "entry_weekday": "TEXT",
    "entry_month": "TEXT",
    "entry_year": "INTEGER",
    "entry_hour": "INTEGER",
    "entry_session": "TEXT",
    "outcome": "TEXT",
    "analytics_timezone": "TEXT",
    "session_timezone": "TEXT",
}

# Stage D appends user-owned annotation fields to the END of the trades table.
STAGE_D_TRADE_COLUMNS = {
    "grade": "TEXT",
    "rule_violation": "TEXT",
    "rule_violation_type": "TEXT",
    "entry_thesis": "TEXT",
    "emotion": "TEXT",
    "primary_screenshot_path": "TEXT",
    "annotation_updated_at_msc": "INTEGER",
}

# Stage E appends advanced, rebuildable analytics. Existing Stage C/D column
# positions remain unchanged.
STAGE_E_TRADE_COLUMNS = {
    "mfe_price": "REAL",
    "mae_price": "REAL",
    "mfe_price_distance": "REAL",
    "mae_price_distance": "REAL",
    "mfe_r": "REAL",
    "mae_r": "REAL",
    "mfe_amount_est": "REAL",
    "mae_amount_est": "REAL",
    "capture_efficiency_pct": "REAL",
    "giveback_r": "REAL",
    "risk_used_pct": "REAL",
    "planned_tp_touched": "TEXT",
    "initial_sl_touched": "TEXT",
    "mfe_time_msc": "INTEGER",
    "mae_time_msc": "INTEGER",
    "excursion_tick_count": "INTEGER",
    "excursion_status": "TEXT",
    "excursion_calculated_at_msc": "INTEGER",
    "excursion_calc_context": "TEXT",
}

# Patch columns are deliberately ensured AFTER Stage E so an upgrade appends
# them to the end of the existing trades table. This preserves prior Stage C/E
# column positions for users whose Excel queries rely on the old export layout.
STAGE_E_SLTP_PATCH_COLUMNS = {
    "initial_sl_set_at_msc": "INTEGER",
    "initial_tp_set_at_msc": "INTEGER",
    "initial_sl_source": "TEXT",
    "initial_tp_source": "TEXT",
}


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=10000;")
    return conn


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict) -> None:
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    for name, sql_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS executions (
            account_login INTEGER NOT NULL,
            deal_ticket INTEGER NOT NULL,
            order_ticket INTEGER,
            position_id INTEGER,
            time INTEGER,
            time_msc INTEGER,
            deal_type INTEGER,
            entry_type INTEGER,
            magic INTEGER,
            reason INTEGER,
            volume REAL,
            price REAL,
            commission REAL,
            swap REAL,
            profit REAL,
            fee REAL,
            sl REAL,
            tp REAL,
            symbol TEXT,
            comment TEXT,
            external_id TEXT,
            PRIMARY KEY (account_login, deal_ticket)
        );

        CREATE INDEX IF NOT EXISTS idx_exec_position
            ON executions(account_login, position_id, time_msc);

        CREATE TABLE IF NOT EXISTS position_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_login INTEGER NOT NULL,
            position_id INTEGER NOT NULL,
            event_time_msc INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            symbol TEXT,
            volume REAL,
            price_open REAL,
            sl REAL,
            tp REAL,
            price_current REAL,
            profit REAL,
            details TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_events_position
            ON position_events(account_login, position_id, event_time_msc);

        CREATE TABLE IF NOT EXISTS position_state (
            account_login INTEGER NOT NULL,
            position_id INTEGER NOT NULL,
            ticket INTEGER,
            symbol TEXT,
            direction TEXT,
            volume REAL,
            price_open REAL,
            sl REAL,
            tp REAL,
            price_current REAL,
            profit REAL,
            swap REAL,
            time_msc INTEGER,
            time_update_msc INTEGER,
            PRIMARY KEY (account_login, position_id)
        );

        CREATE TABLE IF NOT EXISTS trades (
            account_login INTEGER NOT NULL,
            position_id INTEGER NOT NULL,
            symbol TEXT,
            direction TEXT,
            entry_time_msc INTEGER,
            exit_time_msc INTEGER,
            entry_price REAL,
            exit_price REAL,
            entry_volume REAL,
            closed_volume REAL,
            initial_sl REAL,
            initial_tp REAL,
            gross_pnl REAL,
            commission REAL,
            swap REAL,
            fee REAL,
            net_pnl REAL,
            status TEXT,
            strategy TEXT,
            setup TEXT,
            notes TEXT,
            updated_at_msc INTEGER,
            PRIMARY KEY (account_login, position_id)
        );

        CREATE TABLE IF NOT EXISTS account_snapshots (
            snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_login INTEGER NOT NULL,
            time_msc INTEGER NOT NULL,
            balance REAL,
            equity REAL,
            margin REAL,
            margin_free REAL,
            floating_profit REAL
        );

        CREATE INDEX IF NOT EXISTS idx_snapshots_time
            ON account_snapshots(account_login, time_msc);

        CREATE TABLE IF NOT EXISTS sync_state (
            account_login INTEGER NOT NULL,
            state_key TEXT NOT NULL,
            state_value TEXT,
            PRIMARY KEY (account_login, state_key)
        );

        CREATE TABLE IF NOT EXISTS trade_annotation_history (
            revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_login INTEGER NOT NULL,
            position_id INTEGER NOT NULL,
            saved_at_msc INTEGER NOT NULL,
            strategy TEXT,
            setup TEXT,
            grade TEXT,
            rule_violation TEXT,
            rule_violation_type TEXT,
            entry_thesis TEXT,
            emotion TEXT,
            notes TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_annotation_history_trade
            ON trade_annotation_history(account_login, position_id, saved_at_msc);

        CREATE TABLE IF NOT EXISTS trade_screenshots (
            screenshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_login INTEGER NOT NULL,
            position_id INTEGER NOT NULL,
            captured_at_msc INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            source TEXT,
            caption TEXT,
            is_primary INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_trade_screenshots_trade
            ON trade_screenshots(account_login, position_id, captured_at_msc);
        """
    )

    # Non-destructive migrations from Stage A -> B -> D -> E.
    _ensure_columns(conn, "trades", STAGE_B_TRADE_COLUMNS)
    _ensure_columns(conn, "trades", STAGE_D_TRADE_COLUMNS)
    _ensure_columns(conn, "trades", STAGE_E_TRADE_COLUMNS)
    _ensure_columns(conn, "trades", STAGE_E_SLTP_PATCH_COLUMNS)
    conn.commit()


def get_state(conn, account_login: int, key: str):
    row = conn.execute(
        "SELECT state_value FROM sync_state WHERE account_login=? AND state_key=?",
        (account_login, key),
    ).fetchone()
    return row["state_value"] if row else None


def set_state(conn, account_login: int, key: str, value) -> None:
    conn.execute(
        """
        INSERT INTO sync_state(account_login, state_key, state_value)
        VALUES (?, ?, ?)
        ON CONFLICT(account_login, state_key)
        DO UPDATE SET state_value=excluded.state_value
        """,
        (account_login, key, str(value)),
    )
    conn.commit()
