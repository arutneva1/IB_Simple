from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from rich import print

from src.broker.ibkr_client import IBKRClient
from src.core.drift import Drift
from src.core.errors import PlanningError
from src.core.preview import render as render_preview
from src.core.pricing import PricingError, get_price
from src.core.sizing import SizedTrade
from src.io import AppConfig
from src.io.reporting import write_pre_trade_report


class Plan(TypedDict, total=False):
    account_id: str
    drifts: list[Drift]
    trades: list[SizedTrade]
    prices: dict[str, float]
    current: dict[str, float]
    targets: dict[str, float]
    net_liq: float
    pre_gross_exposure: float
    pre_leverage: float
    post_gross_exposure: float
    post_leverage: float
    table: str
    planned_orders: int
    buy_usd: float
    sell_usd: float


async def _fetch_price(ib, symbol: str, cfg) -> tuple[str, float]:
    """Fetch a single symbol's price and return it with the symbol."""

    price = await get_price(
        ib,
        symbol,
        price_source=cfg.pricing.price_source,
        fallback_to_snapshot=cfg.pricing.fallback_to_snapshot,
    )
    return symbol, price


async def plan_account(
    account_id: str,
    portfolios: dict[str, dict[str, float]],
    cfg: AppConfig,
    ts_dt: datetime,
    *,
    client_factory: type[IBKRClient],
    compute_drift,
    prioritize_by_drift,
    size_orders,
    fetch_price=_fetch_price,
    render_preview=render_preview,
    write_pre_trade_report=write_pre_trade_report,
    output_lock: asyncio.Lock | None = None,
) -> Plan:
    """Plan trades for a single account.

    Parameters
    ----------
    account_id:
        The IBKR account identifier.
    portfolios:
        Mapping of symbols to target weightings for different models.
    cfg:
        Account-specific application configuration with overrides already
        applied via :func:`~src.io.config_loader.merge_account_overrides`.
    ts_dt:
        Timestamp used for reporting and logging.
    client_factory, compute_drift, prioritize_by_drift, size_orders,
    fetch_price, render_preview, write_pre_trade_report:
        Dependency injection hooks for testing and custom behaviour.
    output_lock:
        Optional ``asyncio.Lock`` used to serialize ``print`` output when planning
        accounts concurrently.
    """

    async def _print(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        if output_lock is not None:
            async with output_lock:
                print(*args, **kwargs)
        else:
            print(*args, **kwargs)

    await _print(
        f"[blue]Connecting to IBKR at {cfg.ibkr.host}:{cfg.ibkr.port} (client id {cfg.ibkr.client_id}) for account {account_id}[/blue]"
    )
    logging.info(
        "Connecting to IBKR at %s:%s (client id %s) for account %s",
        cfg.ibkr.host,
        cfg.ibkr.port,
        cfg.ibkr.client_id,
        account_id,
    )
    client = client_factory()

    async def _plan_with_client(client):
        await _print("[blue]Retrieving account snapshot[/blue]")
        logging.info("Retrieving account snapshot for %s", account_id)
        snapshot = await client.snapshot(account_id)

        current = {p["symbol"]: float(p["position"]) for p in snapshot["positions"]}
        current["CASH"] = float(snapshot["cash"])

        snapshot_prices: dict[str, float] = {}
        price_timestamps: dict[str, datetime] = {}
        for pos in snapshot["positions"]:
            price = pos.get("market_price") or pos.get("avg_cost")
            if price is not None:
                symbol = pos["symbol"]
                snapshot_prices[symbol] = float(price)
                price_timestamps[symbol] = datetime.utcnow()

        net_liq = float(snapshot.get("net_liq", 0.0))

        targets: dict[str, float] = {}
        for symbol, weights in portfolios.items():
            targets[symbol] = (
                weights.get("smurf", 0.0) * cfg.models.smurf
                + weights.get("badass", 0.0) * cfg.models.badass
                + weights.get("gltr", 0.0) * cfg.models.gltr
            )

        tasks: list[asyncio.Task[Any]] = []
        try:
            target_symbols = {sym for sym in targets if sym != "CASH"}
            await _print(
                f"[blue]Fetching prices for {len(target_symbols)} target symbols[/blue]"
            )
            logging.info(
                "Fetching prices for %s: %d target symbols",
                account_id,
                len(target_symbols),
            )
            tasks = [
                asyncio.create_task(fetch_price(client._ib, sym, cfg))
                for sym in target_symbols
            ]
            for idx, task in enumerate(asyncio.as_completed(tasks), 1):
                try:
                    symbol, price = await task
                except PricingError as exc:
                    await _print(f"[red]{exc}[/red]")
                    logging.error(str(exc))
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise
                snapshot_prices[symbol] = price
                price_timestamps[symbol] = datetime.utcnow()
                await _print(f"[blue]  ({idx}/{len(target_symbols)}) {symbol}[/blue]")
            tasks = []

            await _print("[blue]Computing drift[/blue]")
            logging.info("Computing drift for %s", account_id)
            drifts = compute_drift(
                account_id, current, targets, snapshot_prices, net_liq, cfg
            )
            await _print("[blue]Prioritizing trades[/blue]")
            logging.info("Prioritizing trades for %s", account_id)
            prioritized = prioritize_by_drift(account_id, drifts, cfg)

            trade_symbols = {
                d.symbol
                for d in prioritized
                if d.symbol != "CASH" and d.action in ("BUY", "SELL")
            }

            max_age = getattr(cfg.pricing, "price_max_age_sec", None)
            now = datetime.utcnow()
            trade_prices: dict[str, float] = {}
            stale_symbols: list[str] = []
            for sym in trade_symbols:
                if sym in snapshot_prices:
                    trade_prices[sym] = snapshot_prices[sym]
                    if max_age is not None:
                        ts = price_timestamps.get(sym)
                        if ts is None or (now - ts).total_seconds() > max_age:
                            stale_symbols.append(sym)
                else:
                    stale_symbols.append(sym)

            if stale_symbols:
                await _print(
                    f"[blue]Fetching prices for {len(stale_symbols)} trade symbols[/blue]"
                )
                logging.info(
                    "Fetching prices for %s: %d symbols",
                    account_id,
                    len(stale_symbols),
                )
                tasks = [
                    asyncio.create_task(fetch_price(client._ib, sym, cfg))
                    for sym in stale_symbols
                ]
                for idx, task in enumerate(asyncio.as_completed(tasks), 1):
                    try:
                        symbol, price = await task
                    except PricingError as exc:
                        await _print(f"[red]{exc}[/red]")
                        logging.error(str(exc))
                        for t in tasks:
                            t.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        raise
                    trade_prices[symbol] = price
                    snapshot_prices[symbol] = price
                    price_timestamps[symbol] = datetime.utcnow()
                    await _print(
                        f"[blue]  ({idx}/{len(stale_symbols)}) {symbol}[/blue]"
                    )
                tasks = []
            else:
                await _print("[blue]Reusing existing prices for trade symbols[/blue]")
                logging.info(
                    "Reusing existing prices for %s: %d symbols",
                    account_id,
                    len(trade_symbols),
                )
        except Exception as exc:  # pragma: no cover - defensive
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise PlanningError(str(exc)) from exc
        return (
            current,
            snapshot_prices,
            trade_prices,
            net_liq,
            drifts,
            prioritized,
            targets,
        )

    if hasattr(client, "__aenter__"):
        setattr(client, "_host", cfg.ibkr.host)
        setattr(client, "_port", cfg.ibkr.port)
        setattr(client, "_client_id", cfg.ibkr.client_id)
        async with client:
            (
                current,
                snapshot_prices,
                trade_prices,
                net_liq,
                drifts,
                prioritized,
                targets,
            ) = await _plan_with_client(client)
    else:
        await client.connect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)
        try:
            (
                current,
                snapshot_prices,
                trade_prices,
                net_liq,
                drifts,
                prioritized,
                targets,
            ) = await _plan_with_client(client)
        finally:
            await client.disconnect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)

    await _print("[blue]Sizing orders[/blue]")
    logging.info("Sizing orders for %s", account_id)
    trades, post_gross_exposure, post_leverage = size_orders(
        account_id,
        prioritized,
        trade_prices,
        current,
        current["CASH"],
        net_liq,
        cfg,
    )
    pre_gross_exposure = net_liq - current["CASH"]
    pre_leverage = pre_gross_exposure / net_liq if net_liq else 0.0
    planned_orders = len(trades)
    buy_usd = sum(t.notional for t in trades if t.action == "BUY")
    sell_usd = sum(t.notional for t in trades if t.action == "SELL")
    combined_prices = {**snapshot_prices, **trade_prices}
    pre_path = write_pre_trade_report(
        Path(cfg.io.report_dir),
        ts_dt,
        account_id,
        drifts,
        trades,
        combined_prices,
        net_liq,
        pre_gross_exposure,
        pre_leverage,
        post_gross_exposure,
        post_leverage,
        cfg,
    )
    logging.info("Pre-trade report for %s written to %s", account_id, pre_path)
    await _print("[blue]Rendering preview[/blue]")
    logging.info("Rendering preview for %s", account_id)
    table = render_preview(
        account_id,
        prioritized,
        trades,
        pre_gross_exposure,
        pre_leverage,
        post_gross_exposure,
        post_leverage,
    )

    return {
        "account_id": account_id,
        "drifts": drifts,
        "trades": trades,
        "prices": combined_prices,
        "current": current,
        "targets": targets,
        "net_liq": net_liq,
        "pre_gross_exposure": pre_gross_exposure,
        "pre_leverage": pre_leverage,
        "post_gross_exposure": post_gross_exposure,
        "post_leverage": post_leverage,
        "table": table,
        "planned_orders": planned_orders,
        "buy_usd": buy_usd,
        "sell_usd": sell_usd,
    }
