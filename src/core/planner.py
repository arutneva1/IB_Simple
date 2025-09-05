from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from src.broker.ibkr_client import IBKRClient
from src.core.drift import Drift
from src.core.errors import PlanningError
from src.core.preview import render as render_preview
from src.core.pricing import PricingError, get_price
from src.core.sizing import SizedTrade
from src.io import AppConfig, merge_account_overrides
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
    sell_results: list[dict[str, Any]]
    buy_results: list[dict[str, Any]]
    failed: bool


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
) -> Plan:
    """Plan trades for a single account."""
    cfg = merge_account_overrides(cfg, account_id)

    print(
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
        print("[blue]Retrieving account snapshot[/blue]")
        logging.info("Retrieving account snapshot for %s", account_id)
        snapshot = await client.snapshot(account_id)

        current = {p["symbol"]: float(p["position"]) for p in snapshot["positions"]}
        current["CASH"] = float(snapshot["cash"])

        prices: dict[str, float] = {}
        for pos in snapshot["positions"]:
            price = pos.get("market_price") or pos.get("avg_cost")
            if price is not None:
                prices[pos["symbol"]] = float(price)

        net_liq = float(snapshot.get("net_liq", 0.0))

        targets: dict[str, float] = {}
        for symbol, weights in portfolios.items():
            targets[symbol] = (
                weights["smurf"] * cfg.models.smurf
                + weights["badass"] * cfg.models.badass
                + weights["gltr"] * cfg.models.gltr
            )

        try:
            print("[blue]Computing drift[/blue]")
            logging.info("Computing drift for %s", account_id)
            drifts = compute_drift(account_id, current, targets, prices, net_liq, cfg)
            print("[blue]Prioritizing trades[/blue]")
            logging.info("Prioritizing trades for %s", account_id)
            prioritized = prioritize_by_drift(account_id, drifts, cfg)

            trade_symbols = {
                d.symbol
                for d in prioritized
                if d.symbol != "CASH" and d.action in ("BUY", "SELL")
            }

            print(
                f"[blue]Fetching prices for {len(trade_symbols)} trade symbols[/blue]"
            )
            logging.info(
                "Fetching prices for %s: %d symbols",
                account_id,
                len(trade_symbols),
            )
            tasks = [
                asyncio.create_task(fetch_price(client._ib, sym, cfg))
                for sym in trade_symbols
            ]
            for idx, task in enumerate(asyncio.as_completed(tasks), 1):
                try:
                    symbol, price = await task
                except PricingError as exc:
                    print(f"[red]{exc}[/red]")
                    logging.error(str(exc))
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise
                prices[symbol] = price
                print(f"[blue]  ({idx}/{len(trade_symbols)}) {symbol}[/blue]")

            prices = {sym: prices[sym] for sym in trade_symbols}
        except Exception as exc:  # pragma: no cover - defensive
            raise PlanningError(str(exc)) from exc
        return current, prices, net_liq, drifts, prioritized, targets

    if hasattr(client, "__aenter__"):
        setattr(client, "_host", cfg.ibkr.host)
        setattr(client, "_port", cfg.ibkr.port)
        setattr(client, "_client_id", cfg.ibkr.client_id)
        async with client:
            (
                current,
                prices,
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
                prices,
                net_liq,
                drifts,
                prioritized,
                targets,
            ) = await _plan_with_client(client)
        finally:
            await client.disconnect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)

    print("[blue]Sizing orders[/blue]")
    logging.info("Sizing orders for %s", account_id)
    trades, post_gross_exposure, post_leverage = size_orders(
        account_id,
        prioritized,
        prices,
        current["CASH"],
        net_liq,
        cfg,
    )
    pre_gross_exposure = net_liq - current["CASH"]
    pre_leverage = pre_gross_exposure / net_liq if net_liq else 0.0
    planned_orders = len(trades)
    buy_usd = sum(t.notional for t in trades if t.action == "BUY")
    sell_usd = sum(t.notional for t in trades if t.action == "SELL")
    pre_path = write_pre_trade_report(
        Path(cfg.io.report_dir),
        ts_dt,
        account_id,
        drifts,
        trades,
        prices,
        net_liq,
        pre_gross_exposure,
        pre_leverage,
        post_gross_exposure,
        post_leverage,
        cfg,
    )
    logging.info("Pre-trade report for %s written to %s", account_id, pre_path)
    print("[blue]Rendering preview[/blue]")
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
        "prices": prices,
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
