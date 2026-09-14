from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import time
from typing import Optional

import MetaTrader5 as mt5


def now_msc() -> int:
    return int(time.time() * 1000)


def _utc_dt(msc: int) -> datetime:
    return datetime.fromtimestamp(int(msc) / 1000.0, tz=timezone.utc)


def _safe_profit_estimate(symbol: str, direction: str, volume: float, entry_price: float, close_price: float):
    if not symbol or volume <= 0 or entry_price <= 0 or close_price <= 0:
        return None
    action = mt5.ORDER_TYPE_BUY if str(direction).upper() == "LONG" else mt5.ORDER_TYPE_SELL
    value = mt5.order_calc_profit(action, symbol, float(volume), float(entry_price), float(close_price))
    return None if value is None else float(value)


def _update_extreme(current, price, time_msc, want_max: bool):
    if current is None:
        return (float(price), int(time_msc))
    current_price = current[0]
    if (want_max and price > current_price) or ((not want_max) and price < current_price):
        return (float(price), int(time_msc))
    return current


def calculate_tick_excursion(trade, chunk_hours: int = 6) -> dict:
    """
    Reconstruct MAE/MFE from historical Bid/Ask ticks.

    LONG: liquidation quote is Bid; favorable=max Bid, adverse=min Bid.
    SHORT: liquidation quote is Ask; favorable=min Ask, adverse=max Ask.

    R excursion is based on price distance relative to the original SL distance.
    This avoids repeatedly re-converting old price moves using current FX rates.
    Monetary MFE/MAE are optional estimates using MT5 order_calc_profit() in the
    current terminal environment.
    """
    result = {
        "mfe_price": None,
        "mae_price": None,
        "mfe_price_distance": None,
        "mae_price_distance": None,
        "mfe_r": None,
        "mae_r": None,
        "mfe_amount_est": None,
        "mae_amount_est": None,
        "capture_efficiency_pct": None,
        "giveback_r": None,
        "risk_used_pct": None,
        "planned_tp_touched": None,
        "initial_sl_touched": None,
        "mfe_time_msc": None,
        "mae_time_msc": None,
        "excursion_tick_count": 0,
        "excursion_status": None,
        "excursion_calculated_at_msc": now_msc(),
        "excursion_calc_context": "TICK_HISTORY_BID_ASK",
    }

    if str(trade["status"]).upper() != "CLOSED":
        result["excursion_status"] = "NOT_CLOSED"
        return result

    entry_msc = trade["entry_time_msc"]
    exit_msc = trade["exit_time_msc"]
    symbol = str(trade["symbol"] or "")
    direction = str(trade["direction"] or "").upper()
    entry_price = float(trade["entry_price"] or 0.0)
    initial_sl = float(trade["initial_sl"] or 0.0)
    initial_tp = float(trade["initial_tp"] or 0.0)
    volume = float(trade["entry_volume"] or 0.0)

    if not entry_msc or not exit_msc or exit_msc < entry_msc:
        result["excursion_status"] = "INVALID_TIME_RANGE"
        return result
    if not symbol or direction not in {"LONG", "SHORT"} or entry_price <= 0:
        result["excursion_status"] = "INVALID_TRADE_INPUT"
        return result

    if mt5.symbol_info(symbol) is None:
        result["excursion_status"] = "SYMBOL_UNAVAILABLE"
        return result
    mt5.symbol_select(symbol, True)

    start = _utc_dt(entry_msc)
    end = _utc_dt(exit_msc)
    chunk = timedelta(hours=max(1, int(chunk_hours)))

    # Seed with entry price so a trade with no favorable move has approximately 0 MFE.
    if direction == "LONG":
        favorable = (entry_price, int(entry_msc))
        adverse = (entry_price, int(entry_msc))
    else:
        favorable = (entry_price, int(entry_msc))
        adverse = (entry_price, int(entry_msc))

    total_ticks = 0
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + chunk)
        ticks = mt5.copy_ticks_range(symbol, cursor, chunk_end, mt5.COPY_TICKS_INFO)
        if ticks is None:
            result["excursion_status"] = f"TICK_FETCH_FAILED:{mt5.last_error()}"
            return result

        for tick in ticks:
            bid = float(tick["bid"])
            ask = float(tick["ask"])
            tick_msc = int(tick["time_msc"])
            quote = bid if direction == "LONG" else ask
            if not math.isfinite(quote) or quote <= 0:
                continue
            total_ticks += 1
            if direction == "LONG":
                favorable = _update_extreme(favorable, quote, tick_msc, want_max=True)
                adverse = _update_extreme(adverse, quote, tick_msc, want_max=False)
            else:
                favorable = _update_extreme(favorable, quote, tick_msc, want_max=False)
                adverse = _update_extreme(adverse, quote, tick_msc, want_max=True)

        # Avoid overlapping the exact same millisecond forever while still not
        # leaving a meaningful gap between chunks.
        cursor = chunk_end + timedelta(milliseconds=1)

    if total_ticks == 0:
        result["excursion_status"] = "NO_TICKS"
        return result

    mfe_price, mfe_time = favorable
    mae_price, mae_time = adverse
    if direction == "LONG":
        mfe_distance = mfe_price - entry_price
        mae_distance = mae_price - entry_price
        sl_distance = entry_price - initial_sl if initial_sl > 0 else None
        tp_touched = initial_tp > 0 and mfe_price >= initial_tp
        sl_touched = initial_sl > 0 and mae_price <= initial_sl
    else:
        mfe_distance = entry_price - mfe_price
        mae_distance = entry_price - mae_price  # negative if adverse quote > entry
        sl_distance = initial_sl - entry_price if initial_sl > 0 else None
        tp_touched = initial_tp > 0 and mfe_price <= initial_tp
        sl_touched = initial_sl > 0 and mae_price >= initial_sl

    mfe_r = None
    mae_r = None
    if sl_distance and sl_distance > 0:
        mfe_r = float(mfe_distance / sl_distance)
        mae_r = float(mae_distance / sl_distance)

    realized_r = trade["r_multiple"]
    realized_r = float(realized_r) if realized_r is not None else None
    capture = None
    giveback = None
    if mfe_r is not None and mfe_r > 1e-12 and realized_r is not None:
        capture = 100.0 * realized_r / mfe_r
        giveback = max(0.0, mfe_r - realized_r)

    risk_used = None
    if mae_r is not None:
        risk_used = max(0.0, -mae_r * 100.0)

    result.update(
        {
            "mfe_price": mfe_price,
            "mae_price": mae_price,
            "mfe_price_distance": float(mfe_distance),
            "mae_price_distance": float(mae_distance),
            "mfe_r": mfe_r,
            "mae_r": mae_r,
            "mfe_amount_est": _safe_profit_estimate(symbol, direction, volume, entry_price, mfe_price),
            "mae_amount_est": _safe_profit_estimate(symbol, direction, volume, entry_price, mae_price),
            "capture_efficiency_pct": capture,
            "giveback_r": giveback,
            "risk_used_pct": risk_used,
            "planned_tp_touched": "YES" if tp_touched else "NO",
            "initial_sl_touched": "YES" if sl_touched else "NO",
            "mfe_time_msc": mfe_time,
            "mae_time_msc": mae_time,
            "excursion_tick_count": total_ticks,
            "excursion_status": "CALCULATED",
        }
    )
    return result


def save_excursion(conn, account_login: int, position_id: int, metrics: dict) -> None:
    cols = [
        "mfe_price", "mae_price", "mfe_price_distance", "mae_price_distance",
        "mfe_r", "mae_r", "mfe_amount_est", "mae_amount_est",
        "capture_efficiency_pct", "giveback_r", "risk_used_pct",
        "planned_tp_touched", "initial_sl_touched", "mfe_time_msc", "mae_time_msc",
        "excursion_tick_count", "excursion_status", "excursion_calculated_at_msc",
        "excursion_calc_context",
    ]
    assignments = ", ".join(f"{c}=?" for c in cols)
    values = [metrics.get(c) for c in cols]
    with conn:
        conn.execute(
            f"UPDATE trades SET {assignments} WHERE account_login=? AND position_id=?",
            values + [int(account_login), int(position_id)],
        )


def process_missing_excursions(conn, account_login: int, *, since_msc: Optional[int], limit: int, chunk_hours: int) -> int:
    where = ["account_login=?", "status='CLOSED'", "exit_time_msc IS NOT NULL", "COALESCE(excursion_status,'')='' "]
    params = [int(account_login)]
    if since_msc is not None:
        where.append("exit_time_msc>=?")
        params.append(int(since_msc))
    sql = f"""
        SELECT * FROM trades
        WHERE {' AND '.join(where)}
        ORDER BY exit_time_msc ASC
        LIMIT ?
    """
    params.append(max(1, int(limit)))
    rows = conn.execute(sql, params).fetchall()
    done = 0
    for trade in rows:
        metrics = calculate_tick_excursion(trade, chunk_hours=chunk_hours)
        save_excursion(conn, account_login, int(trade["position_id"]), metrics)
        done += 1
    return done
