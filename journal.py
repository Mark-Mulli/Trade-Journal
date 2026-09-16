import time
from typing import Dict, Iterable

import MetaTrader5 as mt5
import pandas as pd

from analytics import (
    calculate_initial_risk_reward,
    holding_metrics,
    local_time_features,
    outcome_label,
    session_label,
)
from config import ANALYTICS_TIMEZONE, SESSION_TIMEZONE, SESSION_WINDOWS
from database import get_state, set_state

BUY = getattr(mt5, "DEAL_TYPE_BUY", 0)
SELL = getattr(mt5, "DEAL_TYPE_SELL", 1)
ENTRY_IN = getattr(mt5, "DEAL_ENTRY_IN", 0)
ENTRY_OUT = getattr(mt5, "DEAL_ENTRY_OUT", 1)
ENTRY_INOUT = getattr(mt5, "DEAL_ENTRY_INOUT", 2)
ENTRY_OUT_BY = getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)


def now_msc() -> int:
    return int(time.time() * 1000)


def connect_mt5():
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    account = mt5.account_info()
    if account is None:
        raise RuntimeError(f"MT5 account_info failed: {mt5.last_error()}")
    return account


def account_mode_name(margin_mode: int) -> str:
    modes = {
        getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_NETTING", 0): "RETAIL_NETTING",
        getattr(mt5, "ACCOUNT_MARGIN_MODE_EXCHANGE", 1): "EXCHANGE",
        getattr(mt5, "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", 2): "RETAIL_HEDGING",
    }
    return modes.get(margin_mode, f"UNKNOWN({margin_mode})")


def sync_deals(conn, account_login: int, backfill_days: int, overlap_seconds: int) -> int:
    end_ts = int(time.time())
    last_scan = get_state(conn, account_login, "last_deal_scan_ts")
    if last_scan is None:
        start_ts = end_ts - backfill_days * 86400
    else:
        start_ts = max(0, int(last_scan) - overlap_seconds)

    deals = mt5.history_deals_get(start_ts, end_ts)
    if deals is None:
        raise RuntimeError(f"history_deals_get failed: {mt5.last_error()}")

    inserted = 0
    sql = """
        INSERT OR IGNORE INTO executions (
            account_login, deal_ticket, order_ticket, position_id,
            time, time_msc, deal_type, entry_type, magic, reason,
            volume, price, commission, swap, profit, fee, sl, tp,
            symbol, comment, external_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    for d in deals:
        cur = conn.execute(
            sql,
            (
                account_login,
                int(getattr(d, "ticket", 0)),
                int(getattr(d, "order", 0)),
                int(getattr(d, "position_id", 0)),
                int(getattr(d, "time", 0)),
                int(getattr(d, "time_msc", 0)),
                int(getattr(d, "type", -1)),
                int(getattr(d, "entry", -1)),
                int(getattr(d, "magic", 0)),
                int(getattr(d, "reason", 0)),
                float(getattr(d, "volume", 0.0)),
                float(getattr(d, "price", 0.0)),
                float(getattr(d, "commission", 0.0)),
                float(getattr(d, "swap", 0.0)),
                float(getattr(d, "profit", 0.0)),
                float(getattr(d, "fee", 0.0)),
                float(getattr(d, "sl", 0.0)),
                float(getattr(d, "tp", 0.0)),
                str(getattr(d, "symbol", "")),
                str(getattr(d, "comment", "")),
                str(getattr(d, "external_id", "")),
            ),
        )
        inserted += cur.rowcount

    conn.commit()
    set_state(conn, account_login, "last_deal_scan_ts", end_ts)
    return inserted


def _current_positions() -> Dict[int, object]:
    positions = mt5.positions_get()
    if positions is None:
        raise RuntimeError(f"positions_get failed: {mt5.last_error()}")
    result = {}
    for p in positions:
        position_id = int(getattr(p, "identifier", getattr(p, "ticket", 0)))
        result[position_id] = p
    return result


def _direction_from_position_type(position_type: int) -> str:
    return "LONG" if int(position_type) == getattr(mt5, "POSITION_TYPE_BUY", 0) else "SHORT"


def sync_positions_and_events(conn, account_login: int) -> Dict[int, object]:
    current = _current_positions()
    previous_rows = conn.execute(
        "SELECT * FROM position_state WHERE account_login=?", (account_login,)
    ).fetchall()
    previous = {int(r["position_id"]): r for r in previous_rows}

    for position_id, p in current.items():
        curr = {
            "ticket": int(getattr(p, "ticket", 0)),
            "symbol": str(getattr(p, "symbol", "")),
            "direction": _direction_from_position_type(getattr(p, "type", 0)),
            "volume": float(getattr(p, "volume", 0.0)),
            "price_open": float(getattr(p, "price_open", 0.0)),
            "sl": float(getattr(p, "sl", 0.0)),
            "tp": float(getattr(p, "tp", 0.0)),
            "price_current": float(getattr(p, "price_current", 0.0)),
            "profit": float(getattr(p, "profit", 0.0)),
            "swap": float(getattr(p, "swap", 0.0)),
            "time_msc": int(getattr(p, "time_msc", int(getattr(p, "time", 0)) * 1000)),
            "time_update_msc": int(
                getattr(p, "time_update_msc", int(getattr(p, "time_update", 0)) * 1000)
            ),
        }
        prev = previous.get(position_id)

        if prev is None:
            _insert_position_event(conn, account_login, position_id, "OPEN", curr, "")
            # If the logger first sees the position with protection/target already
            # attached, record those first observed values explicitly as well.
            if curr["sl"] > 0:
                _insert_position_event(conn, account_login, position_id, "SL_SET", curr, f'0.0 -> {curr["sl"]}')
            if curr["tp"] > 0:
                _insert_position_event(conn, account_login, position_id, "TP_SET", curr, f'0.0 -> {curr["tp"]}')
        else:
            changes = []
            if abs(curr["volume"] - float(prev["volume"])) > 1e-12:
                changes.append(("VOLUME_CHANGE", f'{prev["volume"]} -> {curr["volume"]}'))

            prev_sl = float(prev["sl"] or 0.0)
            if abs(curr["sl"] - prev_sl) > 1e-12:
                if prev_sl <= 0 < curr["sl"]:
                    event = "SL_SET"
                elif prev_sl > 0 and curr["sl"] <= 0:
                    event = "SL_REMOVED"
                else:
                    event = "SL_CHANGE"
                changes.append((event, f'{prev_sl} -> {curr["sl"]}'))

            prev_tp = float(prev["tp"] or 0.0)
            if abs(curr["tp"] - prev_tp) > 1e-12:
                if prev_tp <= 0 < curr["tp"]:
                    event = "TP_SET"
                elif prev_tp > 0 and curr["tp"] <= 0:
                    event = "TP_REMOVED"
                else:
                    event = "TP_CHANGE"
                changes.append((event, f'{prev_tp} -> {curr["tp"]}'))

            if abs(curr["price_open"] - float(prev["price_open"])) > 1e-12:
                changes.append(("ENTRY_PRICE_CHANGE", f'{prev["price_open"]} -> {curr["price_open"]}'))
            for event_type, details in changes:
                _insert_position_event(conn, account_login, position_id, event_type, curr, details)

        conn.execute(
            """
            INSERT INTO position_state (
                account_login, position_id, ticket, symbol, direction, volume,
                price_open, sl, tp, price_current, profit, swap, time_msc, time_update_msc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_login, position_id) DO UPDATE SET
                ticket=excluded.ticket,
                symbol=excluded.symbol,
                direction=excluded.direction,
                volume=excluded.volume,
                price_open=excluded.price_open,
                sl=excluded.sl,
                tp=excluded.tp,
                price_current=excluded.price_current,
                profit=excluded.profit,
                swap=excluded.swap,
                time_msc=excluded.time_msc,
                time_update_msc=excluded.time_update_msc
            """,
            (
                account_login, position_id, curr["ticket"], curr["symbol"], curr["direction"],
                curr["volume"], curr["price_open"], curr["sl"], curr["tp"],
                curr["price_current"], curr["profit"], curr["swap"],
                curr["time_msc"], curr["time_update_msc"],
            ),
        )

    for position_id, prev in previous.items():
        if position_id not in current:
            state = dict(prev)
            _insert_position_event(conn, account_login, position_id, "CLOSED", state, "")
            conn.execute(
                "DELETE FROM position_state WHERE account_login=? AND position_id=?",
                (account_login, position_id),
            )

    conn.commit()
    return current


def _insert_position_event(conn, account_login, position_id, event_type, state, details):
    event_time = int(state.get("time_update_msc") or state.get("time_msc") or now_msc())
    conn.execute(
        """
        INSERT INTO position_events (
            account_login, position_id, event_time_msc, event_type, symbol,
            volume, price_open, sl, tp, price_current, profit, details
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            account_login, position_id, event_time, event_type,
            state.get("symbol", ""), float(state.get("volume", 0.0)),
            float(state.get("price_open", 0.0)), float(state.get("sl", 0.0)),
            float(state.get("tp", 0.0)), float(state.get("price_current", 0.0)),
            float(state.get("profit", 0.0)), details,
        ),
    )


def _weighted_average(rows: Iterable, price_key="price", volume_key="volume"):
    rows = list(rows)
    total_volume = sum(float(r[volume_key]) for r in rows)
    if total_volume <= 0:
        return None
    return sum(float(r[price_key]) * float(r[volume_key]) for r in rows) / total_volume


def _first_nonzero_event_value(conn, account_login: int, position_id: int, column: str):
    if column not in {"sl", "tp"}:
        raise ValueError("column must be sl or tp")
    row = conn.execute(
        f"""
        SELECT {column} AS value, event_time_msc
        FROM position_events
        WHERE account_login=? AND position_id=? AND COALESCE({column}, 0) > 0
        ORDER BY event_time_msc, event_id
        LIMIT 1
        """,
        (account_login, position_id),
    ).fetchone()
    if not row:
        return None, None
    return float(row["value"]), int(row["event_time_msc"])


def _resolve_initial_level(
    conn, account_login: int, position_id: int, existing_value, existing_time,
    entry_value: float, entry_time_msc: int, live_position, field: str,
):
    """Return the immutable first non-zero SL/TP and its best-known set time/source."""
    if existing_value is not None and float(existing_value) > 0:
        return float(existing_value), existing_time, "LOCKED_EXISTING"

    if entry_value and float(entry_value) > 0:
        return float(entry_value), int(entry_time_msc), "ENTRY_DEAL"

    event_value, event_time = _first_nonzero_event_value(
        conn, account_login, position_id, field
    )
    if event_value is not None:
        return event_value, event_time, "POSITION_EVENT"

    if live_position is not None:
        live_value = float(getattr(live_position, field, 0.0) or 0.0)
        if live_value > 0:
            observed_time = int(
                getattr(
                    live_position,
                    "time_update_msc",
                    int(getattr(live_position, "time_update", 0) or 0) * 1000,
                )
                or now_msc()
            )
            return live_value, observed_time, "LIVE_POSITION_FIRST_OBSERVED"

    return 0.0, existing_time, None


def rebuild_trades(conn, account_login: int, open_positions) -> int:
    position_rows = conn.execute(
        """
        SELECT DISTINCT position_id
        FROM executions
        WHERE account_login=? AND position_id > 0 AND deal_type IN (?, ?)
        """,
        (account_login, BUY, SELL),
    ).fetchall()

    updated = 0
    if hasattr(open_positions, "keys"):
        current_positions = {int(k): v for k, v in open_positions.items()}
        open_ids = set(current_positions)
    else:
        # Backwards-compatible fallback for callers that only provide IDs.
        current_positions = {}
        open_ids = set(int(x) for x in open_positions)
    current_now_msc = now_msc()

    for pr in position_rows:
        position_id = int(pr["position_id"])
        rows = conn.execute(
            """
            SELECT * FROM executions
            WHERE account_login=? AND position_id=?
            ORDER BY time_msc, deal_ticket
            """,
            (account_login, position_id),
        ).fetchall()

        trade_rows = [r for r in rows if int(r["deal_type"]) in (BUY, SELL)]
        if not trade_rows:
            continue

        entry_rows = [r for r in trade_rows if int(r["entry_type"]) == ENTRY_IN]
        exit_rows = [r for r in trade_rows if int(r["entry_type"]) in (ENTRY_OUT, ENTRY_OUT_BY)]
        reverse_rows = [r for r in trade_rows if int(r["entry_type"]) == ENTRY_INOUT]

        # Hedging accounts normally use ENTRY_IN/ENTRY_OUT. Netting reversals
        # still require custom trade-idea splitting for perfect journaling.
        if not entry_rows and reverse_rows:
            entry_rows = [reverse_rows[0]]

        if not entry_rows:
            continue

        first_entry = entry_rows[0]
        direction = "LONG" if int(first_entry["deal_type"]) == BUY else "SHORT"
        symbol = str(first_entry["symbol"])
        entry_price = _weighted_average(entry_rows)
        exit_price = _weighted_average(exit_rows) if exit_rows else None
        entry_volume = sum(float(r["volume"]) for r in entry_rows)
        closed_volume = sum(float(r["volume"]) for r in exit_rows)
        entry_time = min(int(r["time_msc"]) for r in entry_rows)
        exit_time = max((int(r["time_msc"]) for r in exit_rows), default=None)
        entry_deal_sl = float(first_entry["sl"] or 0.0)
        entry_deal_tp = float(first_entry["tp"] or 0.0)

        gross_pnl = sum(float(r["profit"] or 0.0) for r in rows)
        commission = sum(float(r["commission"] or 0.0) for r in rows)
        swap = sum(float(r["swap"] or 0.0) for r in rows)
        fee = sum(float(r["fee"] or 0.0) for r in rows)
        net_pnl = gross_pnl + commission + swap + fee

        status = "OPEN" if position_id in open_ids else "CLOSED"
        if status == "OPEN":
            exit_time = None
            exit_price = None if not exit_rows else exit_price

        existing = conn.execute(
            """
            SELECT initial_sl, initial_tp, initial_sl_set_at_msc, initial_tp_set_at_msc,
                   initial_sl_source, initial_tp_source,
                   risk_amount, planned_reward_amount, planned_rr, risk_status,
                   risk_calculated_at_msc, risk_calc_context
            FROM trades
            WHERE account_login=? AND position_id=?
            """,
            (account_login, position_id),
        ).fetchone()

        live_position = current_positions.get(position_id)
        initial_sl, initial_sl_set_at, initial_sl_source = _resolve_initial_level(
            conn, account_login, position_id,
            existing["initial_sl"] if existing else None,
            existing["initial_sl_set_at_msc"] if existing else None,
            entry_deal_sl, entry_time, live_position, "sl",
        )
        initial_tp, initial_tp_set_at, initial_tp_source = _resolve_initial_level(
            conn, account_login, position_id,
            existing["initial_tp"] if existing else None,
            existing["initial_tp_set_at_msc"] if existing else None,
            entry_deal_tp, entry_time, live_position, "tp",
        )

        existing_risk = float(existing["risk_amount"]) if existing and existing["risk_amount"] is not None else None
        existing_reward = existing["planned_reward_amount"] if existing else None
        existing_rr = existing["planned_rr"] if existing else None

        # Re-run the read-only calculator until the first SL is available. If risk
        # was already frozen but the TP was added later, only fill the missing
        # reward/R:R fields and keep the original risk unchanged.
        risk = calculate_initial_risk_reward(
            mt5,
            symbol=symbol,
            direction=direction,
            volume=entry_volume,
            entry_price=float(entry_price),
            initial_sl=initial_sl,
            initial_tp=initial_tp,
            multi_entry=len(entry_rows) > 1,
        )

        if existing_risk is not None:
            risk_amount = existing_risk
            planned_reward_amount = existing_reward
            planned_rr = existing_rr
            risk_status = existing["risk_status"]
            risk_calculated_at = existing["risk_calculated_at_msc"]
            risk_calc_context = existing["risk_calc_context"]

            if planned_reward_amount is None and risk.get("planned_reward_amount") is not None:
                planned_reward_amount = risk["planned_reward_amount"]
                planned_rr = (
                    float(planned_reward_amount) / float(risk_amount)
                    if risk_amount not in (None, 0) else None
                )
        else:
            risk_amount = risk["risk_amount"]
            planned_reward_amount = risk["planned_reward_amount"]
            planned_rr = risk["planned_rr"]
            risk_status = risk["risk_status"]
            risk_calculated_at = current_now_msc if risk_amount is not None else None
            age_minutes = max(0.0, (current_now_msc - entry_time) / 60000.0)
            risk_calc_context = (
                "NEAR_ENTRY_CURRENT_ENV" if age_minutes <= 10 else "HISTORICAL_RECONSTRUCTION_CURRENT_ENV"
            ) if risk_amount is not None else None

        holding_seconds, holding_minutes = holding_metrics(
            entry_time, exit_time, current_now_msc
        )
        local = local_time_features(entry_time, ANALYTICS_TIMEZONE)
        entry_session = session_label(
            entry_time, SESSION_TIMEZONE, SESSION_WINDOWS
        )
        outcome = outcome_label(status, net_pnl)
        r_multiple = (
            net_pnl / risk_amount
            if status == "CLOSED" and risk_amount not in (None, 0)
            else None
        )

        conn.execute(
            """
            INSERT INTO trades (
                account_login, position_id, symbol, direction,
                entry_time_msc, exit_time_msc, entry_price, exit_price,
                entry_volume, closed_volume, initial_sl, initial_tp,
                initial_sl_set_at_msc, initial_tp_set_at_msc,
                initial_sl_source, initial_tp_source,
                gross_pnl, commission, swap, fee, net_pnl, status,
                risk_amount, planned_reward_amount, planned_rr, r_multiple,
                risk_status, risk_calculated_at_msc, risk_calc_context,
                holding_seconds, holding_minutes,
                entry_datetime_local, entry_date, entry_weekday, entry_month,
                entry_year, entry_hour, entry_session, outcome,
                analytics_timezone, session_timezone, updated_at_msc
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            ON CONFLICT(account_login, position_id) DO UPDATE SET
                symbol=excluded.symbol,
                direction=excluded.direction,
                entry_time_msc=excluded.entry_time_msc,
                exit_time_msc=excluded.exit_time_msc,
                entry_price=excluded.entry_price,
                exit_price=excluded.exit_price,
                entry_volume=excluded.entry_volume,
                closed_volume=excluded.closed_volume,
                initial_sl=CASE
                    WHEN COALESCE(trades.initial_sl,0) > 0 THEN trades.initial_sl
                    ELSE excluded.initial_sl
                END,
                initial_tp=CASE
                    WHEN COALESCE(trades.initial_tp,0) > 0 THEN trades.initial_tp
                    ELSE excluded.initial_tp
                END,
                initial_sl_set_at_msc=COALESCE(trades.initial_sl_set_at_msc, excluded.initial_sl_set_at_msc),
                initial_tp_set_at_msc=COALESCE(trades.initial_tp_set_at_msc, excluded.initial_tp_set_at_msc),
                initial_sl_source=COALESCE(trades.initial_sl_source, excluded.initial_sl_source),
                initial_tp_source=COALESCE(trades.initial_tp_source, excluded.initial_tp_source),
                gross_pnl=excluded.gross_pnl,
                commission=excluded.commission,
                swap=excluded.swap,
                fee=excluded.fee,
                net_pnl=excluded.net_pnl,
                status=excluded.status,
                risk_amount=COALESCE(trades.risk_amount, excluded.risk_amount),
                planned_reward_amount=COALESCE(trades.planned_reward_amount, excluded.planned_reward_amount),
                planned_rr=COALESCE(trades.planned_rr, excluded.planned_rr),
                r_multiple=excluded.r_multiple,
                risk_status=CASE
                    WHEN trades.risk_amount IS NOT NULL THEN trades.risk_status
                    ELSE excluded.risk_status
                END,
                risk_calculated_at_msc=COALESCE(trades.risk_calculated_at_msc, excluded.risk_calculated_at_msc),
                risk_calc_context=COALESCE(trades.risk_calc_context, excluded.risk_calc_context),
                holding_seconds=excluded.holding_seconds,
                holding_minutes=excluded.holding_minutes,
                entry_datetime_local=excluded.entry_datetime_local,
                entry_date=excluded.entry_date,
                entry_weekday=excluded.entry_weekday,
                entry_month=excluded.entry_month,
                entry_year=excluded.entry_year,
                entry_hour=excluded.entry_hour,
                entry_session=excluded.entry_session,
                outcome=excluded.outcome,
                analytics_timezone=excluded.analytics_timezone,
                session_timezone=excluded.session_timezone,
                updated_at_msc=excluded.updated_at_msc
            """,
            (
                account_login, position_id, symbol, direction,
                entry_time, exit_time, entry_price, exit_price,
                entry_volume, closed_volume, initial_sl, initial_tp,
                initial_sl_set_at, initial_tp_set_at,
                initial_sl_source, initial_tp_source,
                gross_pnl, commission, swap, fee, net_pnl, status,
                risk_amount, planned_reward_amount, planned_rr, r_multiple,
                risk_status, risk_calculated_at, risk_calc_context,
                holding_seconds, holding_minutes,
                local["entry_datetime_local"], local["entry_date"],
                local["entry_weekday"], local["entry_month"],
                local["entry_year"], local["entry_hour"], entry_session, outcome,
                ANALYTICS_TIMEZONE, SESSION_TIMEZONE, current_now_msc,
            ),
        )
        updated += 1

    conn.commit()
    return updated


def snapshot_account(conn, account) -> None:
    conn.execute(
        """
        INSERT INTO account_snapshots (
            account_login, time_msc, balance, equity, margin, margin_free, floating_profit
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(account.login), now_msc(), float(account.balance), float(account.equity),
            float(account.margin), float(account.margin_free), float(account.profit),
        ),
    )
    conn.commit()


def export_csvs(conn, account_login: int, export_dir) -> None:
    export_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "trades": "SELECT * FROM trades WHERE account_login=? ORDER BY entry_time_msc",
        "executions": "SELECT * FROM executions WHERE account_login=? ORDER BY time_msc, deal_ticket",
        "position_events": "SELECT * FROM position_events WHERE account_login=? ORDER BY event_time_msc, event_id",
        "account_snapshots": "SELECT * FROM account_snapshots WHERE account_login=? ORDER BY time_msc",
        "trade_annotation_history": "SELECT * FROM trade_annotation_history WHERE account_login=? ORDER BY saved_at_msc, revision_id",
        "trade_screenshots": "SELECT * FROM trade_screenshots WHERE account_login=? ORDER BY captured_at_msc, screenshot_id",
    }
    for name, query in tables.items():
        df = pd.read_sql_query(query, conn, params=(account_login,))
        for col in [c for c in df.columns if c.endswith("_msc")]:    
            df[col.replace("_msc", "_datetime_utc")] = pd.to_datetime(
                df[col], unit="ms", utc=True, errors="coerce"
            )
        df.to_csv(export_dir / f"{name}.csv", index=False)
