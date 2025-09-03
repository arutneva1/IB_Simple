"""Order execution helpers for submitting trades via ib_async."""

from __future__ import annotations

import asyncio
import logging
from datetime import time
from typing import Any, cast
from zoneinfo import ZoneInfo

from ib_async.contract import Stock
from ib_async.order import MarketOrder, TagValue

from src.core.sizing import SizedTrade as Trade
from src.io.config_loader import AppConfig as Config

from .ibkr_client import IBKRClient, IBKRError

log = logging.getLogger(__name__)


async def submit_batch(
    client: IBKRClient, trades: list[Trade], cfg: Config
) -> list[dict[str, Any]]:
    """Submit a batch of market orders and wait for completion.

    Parameters
    ----------
    client:
        Connected :class:`IBKRClient` instance.
    trades:
        Sized trades to execute.
    cfg:
        Application configuration providing execution and rebalance settings.

    Returns
    -------
    list[dict[str, Any]]
        Structured execution results for each trade.
    """

    log.info("Starting batch execution of %d trades", len(trades))
    ib = cast(Any, client._ib)

    if cfg.rebalance.prefer_rth:
        try:
            server_now = await ib.reqCurrentTimeAsync()
        except Exception as exc:  # pragma: no cover - network errors
            raise IBKRError("Failed to query current time") from exc
        if server_now.tzinfo is None:
            server_now = server_now.replace(tzinfo=ZoneInfo("UTC"))
        ny_time = server_now.astimezone(ZoneInfo("America/New_York")).time()
        if not (time(9, 30) <= ny_time <= time(16, 0)):
            raise IBKRError(
                "Current time outside 09:30-16:00 America/New_York; "
                "set rebalance.prefer_rth=False to override"
            )

    async def _wait(trade: Any, symbol: str) -> str:
        terminal = {"Filled", "Cancelled", "ApiCancelled", "Rejected", "Inactive"}
        last_status = ""
        order_id = getattr(getattr(trade, "order", None), "orderId", None)
        while True:
            status = getattr(trade.orderStatus, "status", "")
            if status and status != last_status:
                log.info("Order %s for %s transitioned to %s", order_id, symbol, status)
                last_status = status
            if status in terminal:
                return status
            await trade.statusEvent
            trade.statusEvent.clear()

    async def _submit_one(st: Trade) -> dict[str, Any]:
        contract = Stock(st.symbol, "SMART", "USD")
        order = MarketOrder(st.action, st.quantity)
        algo_used = False
        algo_pref = cfg.execution.algo_preference.lower()
        if algo_pref in {"adaptive", "midprice"}:
            algo_used = True
            if algo_pref == "adaptive":
                order.algoStrategy = "Adaptive"
                order.algoParams = [TagValue("adaptivePriority", "Normal")]
            elif algo_pref == "midprice":
                order.algoStrategy = "ArrivalPx"
                order.algoParams = [TagValue("strategyType", "Midpoint")]
        ib_trade = None
        status = ""
        try:
            ib_trade = ib.placeOrder(contract, order)
            log.info(
                "Submitted order %s for %s",
                getattr(ib_trade.order, "orderId", None),
                st.symbol,
            )
            status = await _wait(ib_trade, st.symbol)
        except Exception:  # pragma: no cover - network errors
            status = "Error"
        if (
            algo_used
            and status in {"Rejected", "Cancelled", "ApiCancelled", "Inactive", "Error"}
            and cfg.execution.fallback_plain_market
        ):
            log.info(
                "Order %s for %s failed with status %s; falling back to plain market",
                getattr(getattr(ib_trade, "order", None), "orderId", None),
                st.symbol,
                status,
            )
            try:
                if ib_trade is not None:
                    ib.cancelOrder(ib_trade.order)
                    await _wait(ib_trade, st.symbol)
            except Exception:  # pragma: no cover - network errors
                pass
            plain = MarketOrder(st.action, st.quantity)
            ib_trade = ib.placeOrder(contract, plain)
            log.info(
                "Submitted fallback order %s for %s",
                getattr(ib_trade.order, "orderId", None),
                st.symbol,
            )
            status = await _wait(ib_trade, st.symbol)
        commission_placeholder = False
        if ib_trade is not None:
            timeout = getattr(cfg.execution, "commission_report_timeout", 5.0)

            def _has_commission(f: Any) -> bool:
                cr = getattr(f, "commissionReport", None)
                if cr is None:
                    return False
                return bool(
                    getattr(cr, "execId", "")
                    or getattr(cr, "commission", 0.0)
                )

            try:
                fills = getattr(ib_trade, "fills", []) or []
                last_counts = (
                    len(fills),
                    sum(1 for f in fills if _has_commission(f)),
                )
                while True:
                    ib_trade.commissionReportEvent.clear()
                    try:
                        await asyncio.wait_for(
                            ib_trade.commissionReportEvent.wait(), timeout=timeout
                        )
                    except asyncio.TimeoutError:
                        fills = getattr(ib_trade, "fills", []) or []
                        counts = (
                            len(fills),
                            sum(1 for f in fills if _has_commission(f)),
                        )
                        if counts == last_counts:
                            if counts[1] == 0:
                                log.warning(
                                    "No commission reports received for order %s",
                                    getattr(ib_trade.order, "orderId", None),
                                )
                            break
                        last_counts = counts
                    else:
                        fills = getattr(ib_trade, "fills", []) or []
                        last_counts = (
                            len(fills),
                            sum(1 for f in fills if _has_commission(f)),
                        )
            except Exception:  # pragma: no cover - defensive
                fills = getattr(ib_trade, "fills", []) or []

            for idx, f in enumerate(fills):
                cr = getattr(f, "commissionReport", None)
                if cr is not None and not _has_commission(f):
                    log.warning(
                        "Fill %d for order %s has placeholder commission report",
                        idx,
                        getattr(ib_trade.order, "orderId", None),
                    )
                    commission_placeholder = True
        filled = getattr(ib_trade.orderStatus, "filled", 0.0) if ib_trade else 0.0
        avg_price = (
            getattr(ib_trade.orderStatus, "avgFillPrice", 0.0) if ib_trade else 0.0
        )
        fill_time = None
        commission = 0.0
        if ib_trade is not None:
            try:
                fills = getattr(ib_trade, "fills", []) or []
                for fill in fills:
                    exec_obj = getattr(fill, "execution", None)
                    if exec_obj is not None:
                        ts = getattr(exec_obj, "time", None)
                        if ts is not None:
                            fill_time = (
                                ts.isoformat() if hasattr(ts, "isoformat") else str(ts)
                            )
                    comm_rep = getattr(fill, "commissionReport", None)
                    if comm_rep is not None:
                        commission += abs(getattr(comm_rep, "commission", 0.0))
                if fill_time is None:
                    ts_attr = getattr(
                        ib_trade.orderStatus, "completedTime", None
                    ) or getattr(ib_trade.orderStatus, "lastTradeTime", None)
                    if ts_attr is not None:
                        fill_time = (
                            ts_attr.isoformat()
                            if hasattr(ts_attr, "isoformat")
                            else str(ts_attr)
                        )
            except Exception:  # pragma: no cover - defensive
                pass
        return {
            "symbol": st.symbol,
            "order_id": getattr(ib_trade.order, "orderId", None) if ib_trade else None,
            "status": status,
            "filled": filled,
            "avg_fill_price": avg_price,
            "fill_qty": filled,
            "fill_price": avg_price,
            "fill_time": fill_time,
            "commission": commission,
            "commission_placeholder": commission_placeholder,
        }

    # Final safeguard: collapse trades with identical symbols and actions.
    combined: dict[tuple[str, str], Trade] = {}
    for t in trades:
        key = (t.symbol, t.action)
        if key in combined:
            existing = combined[key]
            existing.quantity += t.quantity
            existing.notional += t.notional
        else:
            combined[key] = Trade(t.symbol, t.action, t.quantity, t.notional)

    results = list(await asyncio.gather(*[_submit_one(t) for t in combined.values()]))
    status_counts: dict[str, int] = {}
    for res in results:
        status_counts[res["status"]] = status_counts.get(res["status"], 0) + 1
    log.info(
        "Batch execution complete: %d orders with statuses %s",
        len(results),
        status_counts,
    )
    return results


__all__ = ["submit_batch"]
