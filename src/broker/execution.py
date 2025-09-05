"""Order execution helpers for submitting trades via ib_async."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from ib_async.contract import Stock
from ib_async.order import MarketOrder, Order, TagValue

from src.core.sizing import SizedTrade as Trade
from src.io import AppConfig as Config
from src.io import merge_account_overrides

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

    cfg = merge_account_overrides(cfg, account_id)
    log.info("Starting batch execution of %d trades", len(trades))
    ib = cast(Any, client._ib)

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

    async def _wait_with_timeout(trade: Any, symbol: str, timeout: float) -> str:
        try:
            return await asyncio.wait_for(_wait(trade, symbol), timeout)
        except asyncio.TimeoutError as exc:
            raise TimeoutError from exc

    async def _submit_one(st: Trade) -> dict[str, Any]:
        contract = Stock(st.symbol, "SMART", "USD")
        timeout_fill = getattr(cfg.execution, "wait_before_fallback", 300.0)

        def _build_order(qty: float, use_algo: bool) -> tuple[Any, bool]:
            algo_pref = cfg.execution.algo_preference.lower()
            algo_used_local = False
            if use_algo and algo_pref == "midprice":
                order: Any = Order(
                    orderType="MIDPRICE", action=st.action, totalQuantity=qty
                )
                algo_used_local = True
                order.lmtPrice = 0.0
            else:
                order = MarketOrder(st.action, qty)
                if use_algo and algo_pref == "adaptive":
                    algo_used_local = True
                    order.algoStrategy = "Adaptive"
                    order.algoParams = [TagValue("adaptivePriority", "Normal")]
            order.account = account_id
            if cfg.rebalance.trading_hours == "eth":
                order.outsideRth = True
            return order, algo_used_local

        async def _place(qty: float, use_algo: bool, action: str) -> tuple[Any, bool]:
            order, algo_used_local = _build_order(qty, use_algo)
            ib_trade: Any = await retry_async(
                lambda: ib.placeOrder(contract, order),
                action=action,
            )
            log.info(
                "Submitted order %s for %s",
                getattr(ib_trade.order, "orderId", None),
                st.symbol,
            )
            return ib_trade, algo_used_local

        ib_trade, algo_used = await _place(
            st.quantity, True, f"order submission for {st.symbol}"
        )
        status = ""
        fallback_trade: Any | None = None
        try:
            status = await _wait_with_timeout(ib_trade, st.symbol, timeout_fill)
        except TimeoutError:
            status = "Timeout"

        if (
            status != "Filled"
            and (algo_used or status == "Timeout")
            and cfg.execution.fallback_plain_market
        ):
            filled_first = float(getattr(ib_trade.orderStatus, "filled", 0.0))
            remaining_qty = max(st.quantity - filled_first, 0.0)
            log.info(
                "Order %s for %s failed with status %s; cancelling and falling back",
                getattr(getattr(ib_trade, "order", None), "orderId", None),
                st.symbol,
                status,
            )
            try:
                ib.cancelOrder(ib_trade.order)
                await _wait(ib_trade, st.symbol)
            except Exception:  # pragma: no cover - network errors
                pass
            if remaining_qty > 0:
                fallback_trade, _ = await _place(
                    remaining_qty,
                    False,
                    f"fallback order submission for {st.symbol}",
                )
                try:
                    status = await _wait_with_timeout(
                        fallback_trade, st.symbol, timeout_fill
                    )
                except TimeoutError as exc:
                    raise IBKRError(
                        f"order submission for {st.symbol} failed to fill after fallback"
                    ) from exc
            else:
                status = getattr(ib_trade.orderStatus, "status", "")

        if status != "Filled":
            try:
                ib.cancelOrder(ib_trade.order)
                await _wait(ib_trade, st.symbol)
            except Exception as exc:  # pragma: no cover - network errors
                log.warning(
                    "Failed to cancel order %s for %s: %s",
                    getattr(getattr(ib_trade, "order", None), "orderId", None),
                    st.symbol,
                    exc,
                )
            raise IBKRError(
                f"order submission for {st.symbol} failed with status {status}"
            )

        filled_first = float(getattr(ib_trade.orderStatus, "filled", 0.0))
        avg_price_first = float(getattr(ib_trade.orderStatus, "avgFillPrice", 0.0))
        exec_objs = [ib_trade]
        if fallback_trade is not None:
            filled_second = float(getattr(fallback_trade.orderStatus, "filled", 0.0))
            avg_price_second = float(
                getattr(fallback_trade.orderStatus, "avgFillPrice", 0.0)
            )
            filled = filled_first + filled_second
            if filled > 0:
                avg_price = (
                    (filled_first * avg_price_first)
                    + (filled_second * avg_price_second)
                ) / filled
            else:
                avg_price = 0.0  # safeguard: avoid division when nothing filled
            exec_objs.append(fallback_trade)
        else:
            filled = filled_first
            avg_price = (
                avg_price_first if filled_first > 0 else 0.0
            )  # safeguard for zero fill

        commission_placeholder = False
        exec_commissions: dict[str, float] = {}
        timeout_comm = getattr(cfg.execution, "commission_report_timeout", 5.0)

        def _record_reports_from(tr: Any) -> None:
            reports = []
            report_attr = getattr(tr, "commissionReport", None)
            if report_attr is not None:
                reports.append(report_attr)
            reports.extend(getattr(tr, "commissionReports", []) or [])
            client = getattr(ib, "client", None)
            reports.extend(getattr(client, "commissionReports", []) or [])
            for report in reports:
                exec_id = getattr(report, "execId", "")
                if exec_id and exec_id not in exec_commissions:
                    exec_commissions[exec_id] = abs(getattr(report, "commission", 0.0))

        fills_all: list[Any] = []
        for tr in exec_objs:
            try:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + timeout_comm
                poll_interval = min(0.05, timeout_comm)
                client_obj = getattr(ib, "client", None)
                trade_event = getattr(tr, "commissionReportEvent", None)
                client_event = getattr(client_obj, "commissionReportEvent", None)

                while True:
                    fills = getattr(tr, "fills", []) or []
                    _record_reports_from(tr)
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
                            deadline = loop.time() + timeout_comm
                    else:
                        await asyncio.sleep(wait_timeout)
            except Exception:  # pragma: no cover - defensive
                fills = getattr(tr, "fills", []) or []
            else:
                fills = getattr(tr, "fills", []) or []
            fills_all.extend(fills)

        exec_ids = {
            getattr(getattr(f, "execution", None), "execId", "") for f in fills_all
        } - {""}
        if exec_ids and not exec_commissions:
            log.warning(
                "No commission reports received for order %s",
                getattr(ib_trade.order, "orderId", None),
            )

        missing_execs: list[str] = []
        for idx, f in enumerate(fills_all):
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
        commission = sum(exec_commissions.values())
        fill_time = None
        try:
            for fill in fills_all:
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
            "action": st.action,
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

    def _combine(tr_list: list[Trade]) -> list[Trade]:
        combined: dict[tuple[str, str], Trade] = {}
        for t in tr_list:
            key = (t.symbol, t.action)
            if key in combined:
                existing = combined[key]
                existing.quantity += t.quantity
                existing.notional += t.notional
            else:
                combined[key] = Trade(t.symbol, t.action, t.quantity, t.notional)
        return list(combined.values())

    sell_trades = _combine([t for t in trades if t.action == "SELL"])
    buy_trades = _combine([t for t in trades if t.action == "BUY"])

    results: list[dict[str, Any]] = []
    if sell_trades:
        results.extend(await asyncio.gather(*[_submit_one(t) for t in sell_trades]))
    if buy_trades:
        results.extend(await asyncio.gather(*[_submit_one(t) for t in buy_trades]))
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
