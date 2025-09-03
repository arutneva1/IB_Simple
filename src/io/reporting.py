"""Reporting utilities for the rebalance workflow."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from src.core.drift import Drift
from src.core.sizing import SizedTrade

from .config_loader import AppConfig

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
    pre_gross_exposure: float,
    pre_leverage: float,
    post_gross_exposure: float,
    post_leverage: float,
    cfg: AppConfig,
) -> Path:
    """Write a pre-trade CSV report and return its path."""

    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"rebalance_pre_{_format_ts(ts)}.csv"

    fieldnames = [
        "timestamp_run",
        "account_id",
        "symbol",
        "is_cash",
        "target_wt_pct",
        "current_wt_pct",
        "drift_pct",
        "drift_usd",
        "action",
        "qty_shares",
        "est_price",
        "order_type",
        "algo",
        "est_value_usd",
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
                    "drift_usd": d.drift_usd,
                    "action": d.action,
                    "qty_shares": qty,
                    "est_price": est_price,
                    "order_type": order_type,
                    "algo": algo,
                    "est_value_usd": est_value,
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
    pre_gross_exposure: float,
    pre_leverage: float,
    post_gross_exposure: float,
    post_leverage: float,
    cfg: AppConfig,
) -> Path:
    """Write a post-trade CSV report incorporating execution results."""

    report_dir.mkdir(parents=True, exist_ok=True)
    path = report_dir / f"rebalance_post_{_format_ts(ts)}.csv"

    fieldnames = [
        "timestamp_run",
        "account_id",
        "symbol",
        "is_cash",
        "target_wt_pct",
        "current_wt_pct",
        "drift_pct",
        "drift_usd",
        "action",
        "qty_shares",
        "est_price",
        "order_type",
        "algo",
        "est_value_usd",
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

    trades_by_symbol = {t.symbol: t for t in trades}
    results_by_symbol = {r.get("symbol"): r for r in results}
    timestamp_run = ts.isoformat()
    order_type = cfg.execution.order_type
    algo = cfg.execution.algo_preference

    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for d in sorted(drifts, key=lambda d: d.symbol):
            trade = trades_by_symbol.get(d.symbol)
            res = results_by_symbol.get(d.symbol, {})
            planned_qty = trade.quantity if trade else 0.0
            planned_price = (
                trade.notional / trade.quantity if trade and trade.quantity else 0.0
            )
            if d.symbol == "CASH":
                planned_price = 1.0

            fill_qty = res.get("fill_qty")
            if fill_qty is None:
                fill_qty = res.get("filled")
            if fill_qty is None:
                fill_qty = planned_qty

            fill_price = res.get("fill_price")
            if fill_price is None:
                fill_price = res.get("avg_fill_price")
            if fill_price is None:
                fill_price = planned_price

            fill_ts_any = res.get("fill_time")
            if isinstance(fill_ts_any, datetime):
                fill_ts = fill_ts_any.isoformat()
            elif fill_ts_any is None:
                fill_ts = None
            else:
                fill_ts = str(fill_ts_any)

            commission = res.get("commission", 0.0)
            commission_placeholder = res.get("commission_placeholder", False)

            value = fill_qty * fill_price
            writer.writerow(
                {
                    "timestamp_run": timestamp_run,
                    "account_id": account_id,
                    "symbol": d.symbol,
                    "is_cash": d.symbol == "CASH",
                    "target_wt_pct": d.target_wt_pct,
                    "current_wt_pct": d.current_wt_pct,
                    "drift_pct": d.drift_pct,
                    "drift_usd": d.drift_usd,
                    "action": d.action,
                    "qty_shares": fill_qty,
                    "est_price": fill_price,
                    "order_type": order_type,
                    "algo": algo,
                    "est_value_usd": value,
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
                    "notes": res.get("notes", ""),
                }
            )
    log.info("Post-trade report written to %s", path)
    return path


__all__ = [
    "setup_logging",
    "write_pre_trade_report",
    "write_post_trade_report",
]
