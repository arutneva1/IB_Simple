"""Reporting utilities for the rebalance workflow."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.core.drift import Drift
from src.core.sizing import SizedTrade

from . import AppConfig

log = logging.getLogger(__name__)


def _format_ts(ts: datetime) -> str:
    """Return a filesystem-friendly timestamp string."""

    return ts.strftime("%Y%m%d_%H%M%S")


def setup_logging(report_dir: Path, level: str, ts: datetime | str) -> Path:
    """Configure root logging to a timestamped file.

    Parameters
    ----------
    report_dir:
        Directory in which to place the log file. It will be created if
        missing.
    level:
        Logging level name (e.g., ``"INFO"``).
    ts:
        Timestamp used to name the log file.

    Returns
    -------
    Path
        Path to the created log file.
    """

    report_dir.mkdir(parents=True, exist_ok=True)
    ts_str = ts if isinstance(ts, str) else _format_ts(ts)
    log_path = report_dir / f"rebalance_{ts_str}.log"
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        filename=str(log_path),
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return log_path


def write_pre_trade_report(
    report_dir: Path,
    ts: datetime,
    account_id: str,
    drifts: list[Drift],
    trades: list[SizedTrade],
    prices: Mapping[str, float],
    net_liq: float,
    pre_gross_exposure: float,
    pre_leverage: float,
    post_gross_exposure: float,
    post_leverage: float,
    cfg: AppConfig,
) -> Path:
    """Write a pre-trade CSV report and return its path."""

    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"rebalance_pre_{account_id}_{_format_ts(ts)}.csv"

    fieldnames = [
        "timestamp_run",
        "account_id",
        "symbol",
        "is_cash",
        "target_wt_pct",
        "current_wt_pct",
        "drift_pct",
        "drift_pre_buffer_usd",
        "action",
        "qty_shares",
        "est_price",
        "order_type",
        "algo",
        "est_value_usd",
        "planned_value_usd",
        "net_liq",
        "pre_gross_exposure",
        "post_gross_exposure",
        "pre_leverage",
        "post_leverage",
    ]

    trades_by_symbol = {t.symbol: t for t in trades}
    timestamp_run = ts.isoformat()
    order_type = cfg.execution.order_type
    algo = cfg.execution.algo_preference

    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for d in sorted(drifts, key=lambda d: d.symbol):
            trade = trades_by_symbol.get(d.symbol)
            qty = trade.quantity if trade else 0.0
            est_price = prices.get(d.symbol, 1.0 if d.symbol == "CASH" else 0.0)
            est_value = trade.notional if trade else 0.0
            writer.writerow(
                {
                    "timestamp_run": timestamp_run,
                    "account_id": account_id,
                    "symbol": d.symbol,
                    "is_cash": d.symbol == "CASH",
                    "target_wt_pct": d.target_wt_pct,
                    "current_wt_pct": d.current_wt_pct,
                    "drift_pct": d.drift_pct,
                    "drift_pre_buffer_usd": d.drift_usd,
                    "action": d.action,
                    "qty_shares": qty,
                    "est_price": est_price,
                    "order_type": order_type,
                    "algo": algo,
                    "est_value_usd": est_value,
                    "planned_value_usd": est_value,
                    "net_liq": net_liq,
                    "pre_gross_exposure": pre_gross_exposure,
                    "post_gross_exposure": post_gross_exposure,
                    "pre_leverage": pre_leverage,
                    "post_leverage": post_leverage,
                }
            )
    log.info("Pre-trade report written to %s", path)
    return path


def write_post_trade_report(
    report_dir: Path,
    ts: datetime,
    account_id: str,
    drifts: list[Drift],
    trades: list[SizedTrade],
    results: list[dict[str, Any]],
    prices: Mapping[str, float],
    net_liq: float,
    pre_gross_exposure: float,
    pre_leverage: float,
    post_gross_exposure: float,
    post_leverage: float,
    cfg: AppConfig,
) -> Path:
    """Write a post-trade CSV report incorporating execution results.

    Parameters
    ----------
    prices:
        Mapping of symbol to pre-trade estimated prices. These values are
        persisted so that the post-trade report reflects the same estimates
        as the pre-trade report.
    """

    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"rebalance_post_{account_id}_{_format_ts(ts)}.csv"

    fieldnames = [
        "timestamp_run",
        "account_id",
        "symbol",
        "is_cash",
        "target_wt_pct",
        "current_wt_pct",
        "drift_pct",
        "drift_pre_buffer_usd",
        "action",
        "qty_shares",
        "est_price",
        "order_type",
        "algo",
        "est_value_usd",
        "planned_value_usd",
        "net_liq",
        "pre_gross_exposure",
        "post_gross_exposure",
        "pre_leverage",
        "post_leverage",
        "fill_qty",
        "fill_price",
        "fill_timestamp",
        "commission",
        "commission_placeholder",
        "status",
        "error",
        "notes",
    ]

    # Aggregate trades and results across all passes for each (symbol, action)
    aggregated_trades: dict[tuple[str, str], SizedTrade] = {}
    for t in trades:
        trade_key = (t.symbol, t.action)
        if trade_key in aggregated_trades:
            prev = aggregated_trades[trade_key]
            aggregated_trades[trade_key] = SizedTrade(
                t.symbol,
                t.action,
                prev.quantity + t.quantity,
                prev.notional + t.notional,
            )
        else:
            aggregated_trades[trade_key] = SizedTrade(
                t.symbol, t.action, t.quantity, t.notional
            )

    aggregated_results: dict[tuple[str | None, str | None], dict[str, Any]] = {}
    for r in results:
        sym = r.get("symbol")
        if sym is None:
            continue
        act = r.get("action")
        res_key = (sym, act)
        qty_any = r.get("fill_qty")
        if qty_any is None:
            qty_any = r.get("filled", 0.0)
        qty = float(qty_any or 0.0)
        price_any = r.get("fill_price")
        if price_any is None:
            price_any = r.get("avg_fill_price", 0.0)
        price = float(price_any or 0.0)
        exec_comms = r.get("exec_commissions")
        commission: float
        if isinstance(exec_comms, dict) and exec_comms:
            commission = float(sum(exec_comms.values()))
        else:
            commission = float(r.get("commission", 0.0))

        ts_any = r.get("fill_time")
        if isinstance(ts_any, datetime):
            ts_str = ts_any.isoformat()
        elif ts_any is None:
            ts_str = None
        else:
            ts_str = str(ts_any)

        agg = aggregated_results.get(res_key)
        if agg is None:
            aggregated_results[res_key] = {
                "fill_qty": qty,
                "_fill_value": qty * price,
                "fill_price": price,
                "fill_time": ts_str,
                "commission": commission,
                "commission_placeholder": r.get("commission_placeholder", False),
                "status": r.get("status"),
                "error": r.get("error", ""),
                "notes": r.get("notes", ""),
                "missing_exec_ids": list(r.get("missing_exec_ids", [])),
            }
        else:
            agg["fill_qty"] += qty
            agg["_fill_value"] += qty * price
            if ts_str is not None:
                agg["fill_time"] = ts_str
            agg["commission"] += commission
            agg["commission_placeholder"] = agg["commission_placeholder"] or bool(
                r.get("commission_placeholder", False)
            )
            status = r.get("status")
            if status:
                agg["status"] = status
            error = r.get("error")
            if error:
                agg["error"] = "; ".join(filter(None, [agg.get("error", ""), error]))
            notes = r.get("notes")
            if notes:
                agg["notes"] = "; ".join(filter(None, [agg.get("notes", ""), notes]))
            agg.setdefault("missing_exec_ids", [])
            agg["missing_exec_ids"].extend(r.get("missing_exec_ids", []))

    # Finalize aggregated results by computing weighted average fill price
    results_by_key: dict[tuple[str | None, str | None], dict[str, Any]] = {}
    for res_key, agg in aggregated_results.items():
        qty = agg.get("fill_qty", 0.0)
        value = agg.pop("_fill_value", 0.0)
        if qty:
            agg["fill_price"] = value / qty
        results_by_key[res_key] = agg

    trades_by_key = aggregated_trades
    timestamp_run = ts.isoformat()
    order_type = cfg.execution.order_type
    algo = cfg.execution.algo_preference

    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for d in sorted(drifts, key=lambda d: d.symbol):
            trade = trades_by_key.get((d.symbol, d.action))
            res = results_by_key.get((d.symbol, d.action), {})
            planned_qty = trade.quantity if trade else 0.0
            est_price = prices.get(d.symbol, 1.0 if d.symbol == "CASH" else 0.0)
            est_value = trade.notional if trade else 0.0

            fill_qty = res.get("fill_qty")
            if fill_qty is None:
                fill_qty = res.get("filled")
            if fill_qty is None:
                fill_qty = planned_qty

            fill_price = res.get("fill_price")
            if fill_price is None:
                fill_price = res.get("avg_fill_price")
            if fill_price is None:
                fill_price = est_price

            fill_ts_any = res.get("fill_time")
            if isinstance(fill_ts_any, datetime):
                fill_ts = fill_ts_any.isoformat()
            elif fill_ts_any is None:
                fill_ts = None
            else:
                fill_ts = str(fill_ts_any)

            exec_comms = res.get("exec_commissions")
            if isinstance(exec_comms, dict) and exec_comms:
                commission = sum(exec_comms.values())
            else:
                commission = res.get("commission", 0.0)
            commission_placeholder = res.get("commission_placeholder", False)
            notes = res.get("notes", "")
            if commission_placeholder:
                missing_ids = res.get("missing_exec_ids", [])
                if missing_ids:
                    msg = "missing commission execIds: " + ", ".join(missing_ids)
                    notes = f"{notes}; {msg}" if notes else msg

            writer.writerow(
                {
                    "timestamp_run": timestamp_run,
                    "account_id": account_id,
                    "symbol": d.symbol,
                    "is_cash": d.symbol == "CASH",
                    "target_wt_pct": d.target_wt_pct,
                    "current_wt_pct": d.current_wt_pct,
                    "drift_pct": d.drift_pct,
                    "drift_pre_buffer_usd": d.drift_usd,
                    "action": d.action,
                    "qty_shares": planned_qty,
                    "est_price": est_price,
                    "order_type": order_type,
                    "algo": algo,
                    "est_value_usd": est_value,
                    "planned_value_usd": est_value,
                    "net_liq": net_liq,
                    "pre_gross_exposure": pre_gross_exposure,
                    "post_gross_exposure": post_gross_exposure,
                    "pre_leverage": pre_leverage,
                    "post_leverage": post_leverage,
                    "fill_qty": fill_qty,
                    "fill_price": fill_price,
                    "fill_timestamp": fill_ts or "",
                    "commission": commission,
                    "commission_placeholder": commission_placeholder,
                    "status": res.get("status", ""),
                    "error": res.get("error", ""),
                    "notes": notes,
                }
            )
    log.info("Post-trade report written to %s", path)
    return path


def append_run_summary(report_dir: Path, ts: datetime, row: Mapping[str, Any]) -> Path:
    """Append a single row to the run summary CSV file.

    The file is named ``run_summary_<timestamp>.csv`` where ``timestamp`` is
    derived from ``ts`` using :func:`_format_ts`.  A header row is written if the
    file does not yet exist.
    """

    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"run_summary_{_format_ts(ts)}.csv"

    fieldnames = [
        "timestamp_run",
        "account_id",
        "planned_orders",
        "submitted",
        "filled",
        "rejected",
        "buy_usd",
        "sell_usd",
        "pre_leverage",
        "post_leverage",
        "status",
        "error",
    ]

    write_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
    log.info("Run summary appended to %s", path)
    return path


__all__ = [
    "setup_logging",
    "write_pre_trade_report",
    "write_post_trade_report",
    "append_run_summary",
]
