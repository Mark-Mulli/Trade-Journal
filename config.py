from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
EXPORT_DIR = BASE_DIR / "exports"
SCREENSHOT_DIR = BASE_DIR / "screenshots"

DB_PATH = DATA_DIR / "trade_journal.db"

POLL_SECONDS = 2
BACKFILL_DAYS = 30
OVERLAP_SECONDS = 120
ACCOUNT_SNAPSHOT_SECONDS = 60
EXPORT_SECONDS = 10

# Stage B analytics ---------------------------------------------------------
ANALYTICS_TIMEZONE = "Africa/Nairobi"
SESSION_TIMEZONE = "UTC"
SESSION_WINDOWS = [
    ("ASIA", "00:00", "07:00"),
    ("LONDON", "07:00", "12:00"),
    ("LONDON_NY_OVERLAP", "12:00", "16:00"),
    ("NEW_YORK", "16:00", "21:00"),
    ("OFF_HOURS", "21:00", "24:00"),
]

# Stage D annotation app ----------------------------------------------------
# These are suggestions only. Strategy/setup boxes remain editable, so you can
# type your own values and the app will also remember values already in SQLite.
DEFAULT_STRATEGIES = [
    "Trend Following",
    "Breakout",
    "Reversal",
    "Mean Reversion",
    "Liquidity Sweep",
]
DEFAULT_SETUPS = [
    "Pullback",
    "Breakout Retest",
    "Liquidity Sweep",
    "Range Reversal",
    "Continuation",
]
GRADE_OPTIONS = ["A+", "A", "B", "C", "D"]
EMOTION_OPTIONS = ["Calm", "Confident", "Neutral", "Hesitant", "Anxious", "FOMO", "Revenge"]
RECENT_TRADE_LIMIT = 150

# Stage E advanced analytics ------------------------------------------------
# Tick history is processed in chunks to avoid loading very large arrays.
EXCURSION_TICK_CHUNK_HOURS = 6
# Automatic MAE/MFE processing applies to trades that close after Stage E is
# first activated. Use backfill_excursions.py for older closed trades.
AUTO_EXCURSION_BATCH = 2
# Generate summary CSVs periodically for Excel/Power BI.
ADVANCED_REPORT_SECONDS = 60
ROLLING_WINDOW_TRADES = 20
# A small minimum sample threshold used only as a descriptive flag in reports.
MIN_SAMPLE_TRADES = 20
