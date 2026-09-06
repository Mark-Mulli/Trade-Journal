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
