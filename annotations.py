from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Optional

from config import BASE_DIR, SCREENSHOT_DIR


def now_msc() -> int:
    return int(time.time() * 1000)


def normalize_text(value) -> str:
    return (value or "").strip()


def get_accounts(conn):
    rows = conn.execute(
        "SELECT DISTINCT account_login FROM trades ORDER BY account_login"
    ).fetchall()
    return [int(r[0]) for r in rows]


def get_recent_trades(conn, account_login: int, limit: int = 150, filter_mode: str = "ALL"):
    where = ["account_login=?"]
    params = [account_login]
    mode = (filter_mode or "ALL").upper()
    if mode == "OPEN":
        where.append("status='OPEN'")
    elif mode == "CLOSED":
        where.append("status='CLOSED'")
    elif mode == "UNANNOTATED":
        where.append("COALESCE(annotation_updated_at_msc,0)=0")

    query = f"""
        SELECT account_login, position_id, symbol, direction, status,
               entry_datetime_local, entry_price, net_pnl, r_multiple,
               strategy, setup, grade, rule_violation, annotation_updated_at_msc
        FROM trades
        WHERE {' AND '.join(where)}
        ORDER BY entry_time_msc DESC
        LIMIT ?
    """
    params.append(int(limit))
    return conn.execute(query, params).fetchall()


def get_trade(conn, account_login: int, position_id: int):
    return conn.execute(
        "SELECT * FROM trades WHERE account_login=? AND position_id=?",
        (account_login, position_id),
    ).fetchone()


def get_distinct_values(conn, column: str, defaults=None):
    allowed = {"strategy", "setup", "emotion", "rule_violation_type"}
    if column not in allowed:
        raise ValueError("Unsupported annotation vocabulary column")
    values = []
    seen = set()
    for v in defaults or []:
        text = normalize_text(v)
        if text and text.lower() not in seen:
            values.append(text)
            seen.add(text.lower())
    rows = conn.execute(
        f"SELECT DISTINCT {column} FROM trades WHERE TRIM(COALESCE({column},''))<>'' ORDER BY {column}"
    ).fetchall()
    for row in rows:
        text = normalize_text(row[0])
        if text and text.lower() not in seen:
            values.append(text)
            seen.add(text.lower())
    return values


def save_annotation(
    conn,
    account_login: int,
    position_id: int,
    *,
    strategy: str = "",
    setup: str = "",
    grade: str = "",
    rule_violation: str = "NO",
    rule_violation_type: str = "",
    entry_thesis: str = "",
    emotion: str = "",
    notes: str = "",
):
    saved_at = now_msc()
    strategy = normalize_text(strategy)
    setup = normalize_text(setup)
    grade = normalize_text(grade)
    rule_violation = "YES" if str(rule_violation).upper() in {"YES", "TRUE", "1"} else "NO"
    rule_violation_type = normalize_text(rule_violation_type) if rule_violation == "YES" else ""
    entry_thesis = normalize_text(entry_thesis)
    emotion = normalize_text(emotion)
    notes = normalize_text(notes)

    exists = conn.execute(
        "SELECT 1 FROM trades WHERE account_login=? AND position_id=?",
        (account_login, position_id),
    ).fetchone()
    if not exists:
        raise ValueError("Trade no longer exists in the database")

    with conn:
        conn.execute(
            """
            UPDATE trades
            SET strategy=?, setup=?, grade=?, rule_violation=?,
                rule_violation_type=?, entry_thesis=?, emotion=?, notes=?,
                annotation_updated_at_msc=?
            WHERE account_login=? AND position_id=?
            """,
            (
                strategy, setup, grade, rule_violation, rule_violation_type,
                entry_thesis, emotion, notes, saved_at,
                account_login, position_id,
            ),
        )
        conn.execute(
            """
            INSERT INTO trade_annotation_history (
                account_login, position_id, saved_at_msc, strategy, setup,
                grade, rule_violation, rule_violation_type, entry_thesis,
                emotion, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_login, position_id, saved_at, strategy, setup, grade,
                rule_violation, rule_violation_type, entry_thesis, emotion, notes,
            ),
        )
    return saved_at


def screenshot_folder(account_login: int, position_id: int) -> Path:
    path = SCREENSHOT_DIR / str(account_login) / str(position_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _relative_to_base(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR.resolve()))
    except Exception:
        return str(path.resolve())


def resolve_stored_path(stored_path: str) -> Path:
    p = Path(stored_path)
    if p.is_absolute():
        return p
    return BASE_DIR / p


def add_screenshot_record(
    conn,
    account_login: int,
    position_id: int,
    file_path: Path,
    source: str,
    caption: str = "",
    make_primary: bool = True,
):
    captured_at = now_msc()
    stored = _relative_to_base(file_path)
    with conn:
        if make_primary:
            conn.execute(
                "UPDATE trade_screenshots SET is_primary=0 WHERE account_login=? AND position_id=?",
                (account_login, position_id),
            )
        conn.execute(
            """
            INSERT INTO trade_screenshots (
                account_login, position_id, captured_at_msc, file_path,
                source, caption, is_primary
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_login, position_id, captured_at, stored,
                source, normalize_text(caption), 1 if make_primary else 0,
            ),
        )
        if make_primary:
            conn.execute(
                """
                UPDATE trades
                SET primary_screenshot_path=?, annotation_updated_at_msc=?
                WHERE account_login=? AND position_id=?
                """,
                (stored, captured_at, account_login, position_id),
            )
    return stored


def copy_and_register_screenshot(
    conn,
    account_login: int,
    position_id: int,
    source_path: Path,
    caption: str = "",
):
    if not source_path.exists():
        raise FileNotFoundError(source_path)
    folder = screenshot_folder(account_login, position_id)
    suffix = source_path.suffix.lower() or ".png"
    target = folder / f"{time.strftime('%Y%m%d_%H%M%S')}_attached{suffix}"
    counter = 1
    while target.exists():
        target = folder / f"{time.strftime('%Y%m%d_%H%M%S')}_attached_{counter}{suffix}"
        counter += 1
    shutil.copy2(source_path, target)
    return add_screenshot_record(
        conn, account_login, position_id, target, "ATTACHED", caption, True
    )


def list_screenshots(conn, account_login: int, position_id: int):
    return conn.execute(
        """
        SELECT screenshot_id, captured_at_msc, file_path, source, caption, is_primary
        FROM trade_screenshots
        WHERE account_login=? AND position_id=?
        ORDER BY captured_at_msc DESC, screenshot_id DESC
        """,
        (account_login, position_id),
    ).fetchall()


def set_primary_screenshot(conn, account_login: int, position_id: int, screenshot_id: int):
    row = conn.execute(
        """
        SELECT file_path FROM trade_screenshots
        WHERE screenshot_id=? AND account_login=? AND position_id=?
        """,
        (screenshot_id, account_login, position_id),
    ).fetchone()
    if not row:
        raise ValueError("Screenshot not found")
    with conn:
        conn.execute(
            "UPDATE trade_screenshots SET is_primary=0 WHERE account_login=? AND position_id=?",
            (account_login, position_id),
        )
        conn.execute(
            "UPDATE trade_screenshots SET is_primary=1 WHERE screenshot_id=?",
            (screenshot_id,),
        )
        conn.execute(
            "UPDATE trades SET primary_screenshot_path=? WHERE account_login=? AND position_id=?",
            (row["file_path"], account_login, position_id),
        )


def delete_screenshot(conn, account_login: int, position_id: int, screenshot_id: int, delete_file: bool = False):
    row = conn.execute(
        """
        SELECT file_path, is_primary FROM trade_screenshots
        WHERE screenshot_id=? AND account_login=? AND position_id=?
        """,
        (screenshot_id, account_login, position_id),
    ).fetchone()
    if not row:
        return
    with conn:
        conn.execute("DELETE FROM trade_screenshots WHERE screenshot_id=?", (screenshot_id,))
        if int(row["is_primary"] or 0) == 1:
            replacement = conn.execute(
                """
                SELECT screenshot_id, file_path FROM trade_screenshots
                WHERE account_login=? AND position_id=?
                ORDER BY captured_at_msc DESC, screenshot_id DESC LIMIT 1
                """,
                (account_login, position_id),
            ).fetchone()
            if replacement:
                conn.execute("UPDATE trade_screenshots SET is_primary=1 WHERE screenshot_id=?", (replacement["screenshot_id"],))
                conn.execute(
                    "UPDATE trades SET primary_screenshot_path=? WHERE account_login=? AND position_id=?",
                    (replacement["file_path"], account_login, position_id),
                )
            else:
                conn.execute(
                    "UPDATE trades SET primary_screenshot_path=NULL WHERE account_login=? AND position_id=?",
                    (account_login, position_id),
                )
    if delete_file:
        path = resolve_stored_path(row["file_path"])
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass


def annotation_summary_json(conn, account_login: int, position_id: int) -> str:
    trade = get_trade(conn, account_login, position_id)
    if not trade:
        return "{}"
    keys = [
        "strategy", "setup", "grade", "rule_violation", "rule_violation_type",
        "entry_thesis", "emotion", "notes", "primary_screenshot_path",
        "annotation_updated_at_msc",
    ]
    return json.dumps({k: trade[k] for k in keys}, indent=2, default=str)
