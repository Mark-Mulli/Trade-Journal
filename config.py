from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
EXPORT_DIR = BASE_DIR / "exports"

DB_PATH = DATA_DIR / "trade_journal.db"

POLL_SECONDS = 2
BACKFILL_DAYS = 30
OVERLAP_SECONDS = 120
ACCOUNT_SNAPSHOT_SECONDS = 60
EXPORT_SECONDS = 10

# Stage B analytics ---------------------------------------------------------
# Calendar analysis uses the user's local timezone by default.
ANALYTICS_TIMEZONE = "Africa/Nairobi"

# Session labels use fixed UTC windows. These are deliberately configurable.
# They are analysis buckets, not exchange-calendar definitions; DST-aware
# market-session logic can be added later if you need exact London/New York opens.
SESSION_TIMEZONE = "UTC"
SESSION_WINDOWS = [
    ("ASIA", "00:00", "07:00"),
    ("LONDON", "07:00", "12:00"),
    ("LONDON_NY_OVERLAP", "12:00", "16:00"),
    ("NEW_YORK", "16:00", "21:00"),
    ("OFF_HOURS", "21:00", "24:00"),
]
