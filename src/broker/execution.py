"""Order execution helpers for submitting trades via ib_async."""

from __future__ import annotations

import asyncio
from datetime import time
from typing import Any, cast
from zoneinfo import ZoneInfo

from ib_async.contract import Stock
from ib_async.order import MarketOrder, TagValue

from src.core.sizing import SizedTrade as Trade
from src.io.config_loader import AppConfig as Config

from .ibkr_client import IBKRClient, IBKRError


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

    async def _wait(trade: Any) -> str:
        terminal = {"Filled", "Cancelled", "ApiCancelled", "Rejected", "Inactive"}
        while True:
            status = getattr(trade.orderStatus, "status", "")
            if status in terminal:
                return status
            await trade.updateEvent.wait()
            trade.updateEvent.clear()

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
            status = await _wait(ib_trade)
        except Exception:  # pragma: no cover - network errors
            status = "Error"
        if (
            algo_used
            and status in {"Rejected", "Cancelled", "ApiCancelled", "Inactive", "Error"}
            and cfg.execution.fallback_plain_market
        ):
            plain = MarketOrder(st.action, st.quantity)
            ib_trade = ib.placeOrder(contract, plain)
            status = await _wait(ib_trade)
        return {
            "symbol": st.symbol,
            "order_id": getattr(ib_trade.order, "orderId", None) if ib_trade else None,
            "status": status,
            "filled": getattr(ib_trade.orderStatus, "filled", 0.0) if ib_trade else 0.0,
            "avg_fill_price": (
                getattr(ib_trade.orderStatus, "avgFillPrice", 0.0) if ib_trade else 0.0
            ),
        }

    return list(await asyncio.gather(*[_submit_one(t) for t in trades]))


__all__ = ["submit_batch"]
