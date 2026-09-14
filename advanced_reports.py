from __future__ import annotations

from pathlib import Path
import math
import pandas as pd


def _safe_div(num, den):
    try:
        if den is None or abs(float(den)) < 1e-12:
            return None
        return float(num) / float(den)
    except Exception:
        return None


def _profit_factor(series: pd.Series):
    s = pd.to_numeric(series, errors="coerce").dropna()
    gains = s[s > 0].sum()
    losses = -s[s < 0].sum()
    if losses <= 0:
        return None if gains <= 0 else float("inf")
    return float(gains / losses)


def _group_summary(group: pd.DataFrame, min_sample: int) -> dict:
    closed = group[group["status"].astype(str).str.upper().eq("CLOSED")].copy()
    r = pd.to_numeric(closed.get("r_multiple"), errors="coerce")
    pnl = pd.to_numeric(closed.get("net_pnl"), errors="coerce")
    winners = closed[closed["outcome"].astype(str).str.upper().eq("WIN")]
    losers = closed[closed["outcome"].astype(str).str.upper().eq("LOSS")]
    win_r = pd.to_numeric(winners.get("r_multiple"), errors="coerce").dropna()
    loss_r = pd.to_numeric(losers.get("r_multiple"), errors="coerce").dropna()
    n = int(len(closed))
    result = {
        "trades": n,
        "wins": int(len(winners)),
        "losses": int(len(losers)),
        "breakeven": int(closed["outcome"].astype(str).str.upper().eq("BREAKEVEN").sum()),
        "win_rate": _safe_div(len(winners), n),
        "net_pnl": float(pnl.sum()) if len(pnl) else 0.0,
        "avg_pnl": float(pnl.mean()) if pnl.notna().any() else None,
        "avg_r": float(r.mean()) if r.notna().any() else None,
        "median_r": float(r.median()) if r.notna().any() else None,
        "profit_factor": _profit_factor(pnl),
        "avg_winner_r": float(win_r.mean()) if len(win_r) else None,
        "avg_loser_r": float(loss_r.mean()) if len(loss_r) else None,
        "payoff_ratio": _safe_div(win_r.mean() if len(win_r) else None, abs(loss_r.mean()) if len(loss_r) else None),
        "avg_holding_minutes": pd.to_numeric(closed.get("holding_minutes"), errors="coerce").mean(),
        "avg_planned_rr": pd.to_numeric(closed.get("planned_rr"), errors="coerce").mean(),
        "avg_mfe_r": pd.to_numeric(closed.get("mfe_r"), errors="coerce").mean(),
        "avg_mae_r": pd.to_numeric(closed.get("mae_r"), errors="coerce").mean(),
        "avg_capture_efficiency_pct": pd.to_numeric(closed.get("capture_efficiency_pct"), errors="coerce").mean(),
        "avg_risk_used_pct": pd.to_numeric(closed.get("risk_used_pct"), errors="coerce").mean(),
        "sample_flag": "OK" if n >= int(min_sample) else "LOW_SAMPLE",
    }
    return result


def _dimension_report(df: pd.DataFrame, column: str, min_sample: int) -> pd.DataFrame:
    if column not in df.columns:
        return pd.DataFrame()
    work = df.copy()
    label = work[column].fillna("").astype(str).str.strip().replace("", "(blank)")
    work = work.assign(_dimension=label)
    rows = []
    for value, group in work.groupby("_dimension", dropna=False):
        row = {column: value}
        row.update(_group_summary(group, min_sample))
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    out = pd.DataFrame(rows)
    return out.sort_values(["trades", "net_pnl"], ascending=[False, False], na_position="last")


def _closed_trade_sequence(df: pd.DataFrame, rolling_window: int) -> pd.DataFrame:
    closed = df[df["status"].astype(str).str.upper().eq("CLOSED")].copy()
    if closed.empty:
        return pd.DataFrame()
    closed["exit_time_msc"] = pd.to_numeric(closed["exit_time_msc"], errors="coerce")
    closed = closed.sort_values(["exit_time_msc", "position_id"], na_position="last").reset_index(drop=True)
    closed["trade_number"] = range(1, len(closed) + 1)
    closed["net_pnl_num"] = pd.to_numeric(closed["net_pnl"], errors="coerce").fillna(0.0)
    closed["r_num"] = pd.to_numeric(closed["r_multiple"], errors="coerce")
    closed["cumulative_pnl"] = closed["net_pnl_num"].cumsum()
    closed["cumulative_r"] = closed["r_num"].fillna(0.0).cumsum()
    closed["running_peak_pnl"] = closed["cumulative_pnl"].cummax()
    closed["closed_trade_drawdown"] = closed["cumulative_pnl"] - closed["running_peak_pnl"]

    window = max(2, int(rolling_window))
    closed[f"rolling_{window}_avg_r"] = closed["r_num"].rolling(window, min_periods=1).mean()
    win_indicator = closed["outcome"].astype(str).str.upper().eq("WIN").astype(float)
    closed[f"rolling_{window}_win_rate"] = win_indicator.rolling(window, min_periods=1).mean()

    pf_values = []
    for i in range(len(closed)):
        start = max(0, i - window + 1)
        pf_values.append(_profit_factor(closed.loc[start:i, "net_pnl_num"]))
    closed[f"rolling_{window}_profit_factor"] = pf_values

    win_streak = 0
    loss_streak = 0
    win_streaks = []
    loss_streaks = []
    for outcome in closed["outcome"].astype(str).str.upper():
        if outcome == "WIN":
            win_streak += 1
            loss_streak = 0
        elif outcome == "LOSS":
            loss_streak += 1
            win_streak = 0
        else:
            win_streak = 0
            loss_streak = 0
        win_streaks.append(win_streak)
        loss_streaks.append(loss_streak)
    closed["win_streak"] = win_streaks
    closed["loss_streak"] = loss_streaks

    columns = [
        "trade_number", "position_id", "symbol", "direction", "exit_time_msc",
        "entry_date", "strategy", "setup", "grade", "rule_violation",
        "outcome", "net_pnl_num", "r_num", "mfe_r", "mae_r",
        "capture_efficiency_pct", "cumulative_pnl", "cumulative_r",
        "running_peak_pnl", "closed_trade_drawdown",
        f"rolling_{window}_avg_r", f"rolling_{window}_win_rate",
        f"rolling_{window}_profit_factor", "win_streak", "loss_streak",
    ]
    return closed[[c for c in columns if c in closed.columns]]


def _account_drawdown(snapshots: pd.DataFrame) -> dict:
    if snapshots.empty or "equity" not in snapshots.columns:
        return {"max_sampled_equity_drawdown": None, "max_sampled_equity_drawdown_pct": None}
    eq = pd.to_numeric(snapshots["equity"], errors="coerce").dropna()
    if eq.empty:
        return {"max_sampled_equity_drawdown": None, "max_sampled_equity_drawdown_pct": None}
    peak = eq.cummax()
    dd = eq - peak
    dd_pct = dd / peak.replace(0, math.nan)
    return {
        "max_sampled_equity_drawdown": float(dd.min()),
        "max_sampled_equity_drawdown_pct": float(dd_pct.min()) if dd_pct.notna().any() else None,
    }


def generate_advanced_reports(conn, account_login: int, export_dir: Path, *, rolling_window: int = 20, min_sample: int = 20) -> None:
    export_dir.mkdir(parents=True, exist_ok=True)
    trades = pd.read_sql_query(
        "SELECT * FROM trades WHERE account_login=? ORDER BY entry_time_msc",
        conn, params=(int(account_login),),
    )
    snapshots = pd.read_sql_query(
        "SELECT * FROM account_snapshots WHERE account_login=? ORDER BY time_msc",
        conn, params=(int(account_login),),
    )

    if trades.empty:
        pd.DataFrame().to_csv(export_dir / "performance_summary.csv", index=False)
        return

    sequence = _closed_trade_sequence(trades, rolling_window)
    sequence.to_csv(export_dir / "rolling_performance.csv", index=False)

    dims = [
        "strategy", "setup", "symbol", "entry_session", "entry_weekday",
        "direction", "grade", "emotion", "rule_violation", "rule_violation_type",
    ]
    for dim in dims:
        _dimension_report(trades, dim, min_sample).to_csv(export_dir / f"analysis_by_{dim}.csv", index=False)

    # Calendar summaries retain chronological labels and are convenient for Excel.
    for dim in ["entry_date", "entry_month", "entry_year"]:
        _dimension_report(trades, dim, min_sample=1).to_csv(export_dir / f"analysis_by_{dim}.csv", index=False)

    closed = trades[trades["status"].astype(str).str.upper().eq("CLOSED")]
    overall = _group_summary(closed, min_sample)
    overall.update(_account_drawdown(snapshots))
    if not sequence.empty:
        overall["max_closed_trade_drawdown"] = float(pd.to_numeric(sequence["closed_trade_drawdown"], errors="coerce").min())
        overall["longest_win_streak"] = int(pd.to_numeric(sequence["win_streak"], errors="coerce").max())
        overall["longest_loss_streak"] = int(pd.to_numeric(sequence["loss_streak"], errors="coerce").max())
    else:
        overall["max_closed_trade_drawdown"] = None
        overall["longest_win_streak"] = 0
        overall["longest_loss_streak"] = 0

    excursion_status = trades.get("excursion_status", pd.Series(dtype="object")).fillna("").astype(str)
    overall["excursion_calculated_trades"] = int(excursion_status.eq("CALCULATED").sum())
    overall["excursion_coverage_pct"] = _safe_div(overall["excursion_calculated_trades"], len(closed))
    pd.DataFrame([overall]).to_csv(export_dir / "performance_summary.csv", index=False)
