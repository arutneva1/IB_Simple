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
from src.io import AppConfig as Config

from .errors import IBKRError
from .ibkr_client import IBKRClient
from .utils import retry_async

log = logging.getLogger(__name__)


async def submit_batch(
    client: IBKRClient, trades: list[Trade], cfg: Config, account_id: str
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
    account_id:
        Account to assign to each order.

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
        order.account = account_id
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
        ib_trade: Any = await retry_async(
            lambda: ib.placeOrder(contract, order),
            action=f"order submission for {st.symbol}",
        )
        log.info(
            "Submitted order %s for %s",
            getattr(ib_trade.order, "orderId", None),
            st.symbol,
        )
        status = ""
        try:
            status = await _wait(ib_trade, st.symbol)
        except Exception as exc:  # pragma: no cover - network errors
            raise IBKRError(f"order submission for {st.symbol} failed: {exc}") from exc
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
                ib.cancelOrder(ib_trade.order)
                await _wait(ib_trade, st.symbol)
            except Exception:  # pragma: no cover - network errors
                pass
            plain = MarketOrder(st.action, st.quantity)
            ib_trade = await retry_async(
                lambda: ib.placeOrder(contract, plain),
                action=f"fallback order submission for {st.symbol}",
            )
            log.info(
                "Submitted fallback order %s for %s",
                getattr(ib_trade.order, "orderId", None),
                st.symbol,
            )
            status = await _wait(ib_trade, st.symbol)
        commission_placeholder = False
        exec_commissions: dict[str, float] = {}
        timeout = getattr(cfg.execution, "commission_report_timeout", 5.0)

        def _record_reports() -> None:
            reports = []
            report_attr = getattr(ib_trade, "commissionReport", None)
            if report_attr is not None:
                reports.append(report_attr)
            reports.extend(getattr(ib_trade, "commissionReports", []) or [])
            client = getattr(ib, "client", None)
            reports.extend(getattr(client, "commissionReports", []) or [])
            for report in reports:
                exec_id = getattr(report, "execId", "")
                if exec_id and exec_id not in exec_commissions:
                    exec_commissions[exec_id] = abs(getattr(report, "commission", 0.0))

        try:
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            poll_interval = min(0.05, timeout)
            client_obj = getattr(ib, "client", None)
            trade_event = getattr(ib_trade, "commissionReportEvent", None)
            client_event = getattr(client_obj, "commissionReportEvent", None)

            while True:
                fills = getattr(ib_trade, "fills", []) or []
                _record_reports()
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break

                wait_timeout = min(poll_interval, remaining)
                if trade_event is not None:
                    trade_event.clear()
                if client_event is not None:
                    client_event.clear()
                events = [
                    asyncio.create_task(e.wait())
                    for e in (trade_event, client_event)
                    if e is not None
                ]
                if events:
                    done, pending = await asyncio.wait(
                        events,
                        timeout=wait_timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for p in pending:
                        p.cancel()
                    if done:
                        deadline = loop.time() + timeout
                else:
                    await asyncio.sleep(wait_timeout)
        except Exception:  # pragma: no cover - defensive
            fills = getattr(ib_trade, "fills", []) or []
        else:
            fills = getattr(ib_trade, "fills", []) or []

        exec_ids = {
            getattr(getattr(f, "execution", None), "execId", "") for f in fills
        } - {""}
        if exec_ids and not exec_commissions:
            log.warning(
                "No commission reports received for order %s",
                getattr(ib_trade.order, "orderId", None),
            )

        missing_execs: list[str] = []
        for idx, f in enumerate(fills):
            exec_obj = getattr(f, "execution", None)
            exec_id = getattr(exec_obj, "execId", "")
            if exec_id and exec_id not in exec_commissions:
                log.warning(
                    "No commission report for execId %s in fill %d for order %s",
                    exec_id,
                    idx,
                    getattr(ib_trade.order, "orderId", None),
                )
                commission_placeholder = True
                missing_execs.append(exec_id)
        filled = getattr(ib_trade.orderStatus, "filled", 0.0)
        avg_price = getattr(ib_trade.orderStatus, "avgFillPrice", 0.0)
        fill_time = None
        commission = sum(exec_commissions.values())
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
            "order_id": getattr(ib_trade.order, "orderId", None),
            "status": status,
            "filled": filled,
            "avg_fill_price": avg_price,
            "fill_qty": filled,
            "fill_price": avg_price,
            "fill_time": fill_time,
            "commission": commission,
            "exec_commissions": exec_commissions,
            "commission_placeholder": commission_placeholder,
            "missing_exec_ids": missing_execs,
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
