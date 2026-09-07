from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Iterable, Optional, Sequence, Tuple


def utc_datetime_from_msc(msc: int) -> datetime:
    return datetime.fromtimestamp(int(msc) / 1000.0, tz=timezone.utc)


def local_time_features(msc: int, timezone_name: str) -> dict:
    """Derive stable calendar fields from an MT5 epoch-millisecond timestamp."""
    dt = utc_datetime_from_msc(msc).astimezone(ZoneInfo(timezone_name))
    return {
        "entry_datetime_local": dt.isoformat(timespec="seconds"),
        "entry_date": dt.date().isoformat(),
        "entry_weekday": dt.strftime("%A"),
        "entry_month": dt.strftime("%B"),
        "entry_year": dt.year,
        "entry_hour": dt.hour,
    }


def _parse_hhmm(value: str) -> int:
    hour, minute = value.split(":", 1)
    h, m = int(hour), int(minute)
    if h == 24 and m == 0:
        return 24 * 60
    if not (0 <= h <= 23 and 0 <= m <= 59):
        raise ValueError(f"Invalid HH:MM value: {value}")
    return h * 60 + m


def session_label(
    msc: int,
    timezone_name: str,
    windows: Sequence[Tuple[str, str, str]],
    default: str = "UNCLASSIFIED",
) -> str:
    """
    Classify an entry timestamp into a configured session window.

    Windows are evaluated in order. Each item is (label, start_hhmm, end_hhmm).
    Wrap-around windows such as 21:00 -> 03:00 are supported.
    """
    dt = utc_datetime_from_msc(msc).astimezone(ZoneInfo(timezone_name))
    minute_of_day = dt.hour * 60 + dt.minute

    for label, start_text, end_text in windows:
        start = _parse_hhmm(start_text)
        end = _parse_hhmm(end_text)
        if start == end:
            continue
        if start < end:
            if start <= minute_of_day < end:
                return label
        else:  # wraps midnight
            if minute_of_day >= start or minute_of_day < end:
                return label
    return default


def holding_metrics(entry_time_msc: int, exit_time_msc: Optional[int], now_msc: int) -> tuple[int, float]:
    end = int(exit_time_msc) if exit_time_msc else int(now_msc)
    seconds = max(0, int(round((end - int(entry_time_msc)) / 1000.0)))
    return seconds, seconds / 60.0


def outcome_label(status: str, net_pnl: float, tolerance: float = 1e-9) -> str:
    if status != "CLOSED":
        return "OPEN"
    if net_pnl > tolerance:
        return "WIN"
    if net_pnl < -tolerance:
        return "LOSS"
    return "BREAKEVEN"


def _ensure_symbol_ready(mt5_module, symbol: str) -> bool:
    info = mt5_module.symbol_info(symbol)
    if info is None:
        return False
    if not bool(getattr(info, "visible", True)):
        return bool(mt5_module.symbol_select(symbol, True))
    return True


def calculate_initial_risk_reward(
    mt5_module,
    symbol: str,
    direction: str,
    volume: float,
    entry_price: float,
    initial_sl: float,
    initial_tp: float,
    multi_entry: bool = False,
) -> dict:
    """
    Calculate price-risk and planned reward in account currency using MT5's
    order_calc_profit(). No orders are sent.

    For historical trades MT5 evaluates using the current trading environment,
    so the first successful result should be persisted rather than recalculated forever.
    """
    result = {
        "risk_amount": None,
        "planned_reward_amount": None,
        "planned_rr": None,
        "risk_status": None,
    }

    if not symbol or volume <= 0 or entry_price <= 0:
        result["risk_status"] = "INVALID_TRADE_INPUT"
        return result

    if not initial_sl or initial_sl <= 0:
        result["risk_status"] = "NO_INITIAL_SL"
        return result

    direction = direction.upper()
    if direction == "LONG":
        action = mt5_module.ORDER_TYPE_BUY
        valid_sl = initial_sl < entry_price
        valid_tp = bool(initial_tp and initial_tp > entry_price)
    elif direction == "SHORT":
        action = mt5_module.ORDER_TYPE_SELL
        valid_sl = initial_sl > entry_price
        valid_tp = bool(initial_tp and initial_tp < entry_price)
    else:
        result["risk_status"] = "INVALID_DIRECTION"
        return result

    if not valid_sl:
        result["risk_status"] = "INVALID_SL_SIDE"
        return result

    if not _ensure_symbol_ready(mt5_module, symbol):
        result["risk_status"] = "SYMBOL_UNAVAILABLE"
        return result

    sl_profit = mt5_module.order_calc_profit(action, symbol, volume, entry_price, initial_sl)
    if sl_profit is None:
        result["risk_status"] = f"RISK_CALC_FAILED:{mt5_module.last_error()}"
        return result

    risk_amount = abs(float(sl_profit))
    if risk_amount <= 0:
        result["risk_status"] = "ZERO_RISK"
        return result

    result["risk_amount"] = risk_amount
    result["risk_status"] = "CALCULATED_MULTI_ENTRY_APPROX" if multi_entry else "CALCULATED"

    if valid_tp:
        tp_profit = mt5_module.order_calc_profit(action, symbol, volume, entry_price, initial_tp)
        if tp_profit is not None:
            reward = max(0.0, float(tp_profit))
            result["planned_reward_amount"] = reward
            result["planned_rr"] = reward / risk_amount if risk_amount else None

    return result
