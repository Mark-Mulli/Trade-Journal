import sqlite3
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


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
        """
    )
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
