# isort: skip_file
"""Rebalance CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from rich import print

from src.broker.execution import submit_batch
from src.broker.ibkr_client import IBKRError, IBKRClient
from src.core.drift import compute_drift, prioritize_by_drift
from src.core.preview import render as render_preview
from src.core.pricing import PricingError, get_price
from src.core.sizing import size_orders
from src.io.config_loader import ConfigError, load_config
from src.io.portfolio_csv import PortfolioCSVError, load_portfolios
from src.io.reporting import (
    setup_logging,
    write_post_trade_report,
    write_pre_trade_report,
)


async def _fetch_price(ib, symbol: str, cfg) -> tuple[str, float]:
    """Fetch a single symbol's price and return it with the symbol."""

    price = await get_price(
        ib,
        symbol,
        price_source=cfg.pricing.price_source,
        fallback_to_snapshot=cfg.pricing.fallback_to_snapshot,
    )
    return symbol, price


async def _run(args: argparse.Namespace) -> None:
    cfg_path = Path(args.config)
    csv_path = Path(args.csv)
    print(f"[blue]Loading configuration from {cfg_path}[/blue]")
    cfg = load_config(cfg_path)
    ts_dt = datetime.now(timezone.utc)
    timestamp = ts_dt.strftime("%Y%m%dT%H%M%S")
    setup_logging(Path(cfg.io.report_dir), cfg.io.log_level, timestamp)
    logging.info("Loaded configuration from %s", cfg_path)

    print(f"[blue]Loading portfolios from {csv_path}[/blue]")
    logging.info("Loading portfolios from %s", csv_path)
    portfolios = await load_portfolios(
        csv_path,
        host=cfg.ibkr.host,
        port=cfg.ibkr.port,
        client_id=cfg.ibkr.client_id,
    )

    client = IBKRClient()
    print(
        f"[blue]Connecting to IBKR at {cfg.ibkr.host}:{cfg.ibkr.port} (client id {cfg.ibkr.client_id})[/blue]"
    )
    logging.info(
        "Connecting to IBKR at %s:%s (client id %s)",
        cfg.ibkr.host,
        cfg.ibkr.port,
        cfg.ibkr.client_id,
    )
    await client.connect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)
    try:
        print("[blue]Retrieving account snapshot[/blue]")
        logging.info("Retrieving account snapshot")
        snapshot = await client.snapshot(cfg.ibkr.account_id)

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

        print("[blue]Computing drift[/blue]")
        logging.info("Computing drift")
        drifts = compute_drift(current, targets, prices, net_liq, cfg)
        print("[blue]Prioritizing trades[/blue]")
        logging.info("Prioritizing trades")
        prioritized = prioritize_by_drift(drifts, cfg)

        trade_symbols = {
            d.symbol
            for d in prioritized
            if d.symbol != "CASH" and d.action in ("BUY", "SELL")
        }

        print(f"[blue]Fetching prices for {len(trade_symbols)} trade symbols[/blue]")
        logging.info("Fetching prices for %d symbols", len(trade_symbols))
        tasks = [
            asyncio.create_task(_fetch_price(client._ib, sym, cfg))
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
                raise SystemExit(1)
            prices[symbol] = price
            print(f"[blue]  ({idx}/{len(trade_symbols)}) {symbol}[/blue]")

        prices = {sym: prices[sym] for sym in trade_symbols}
    finally:
        await client.disconnect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)

    print("[blue]Sizing orders[/blue]")
    logging.info("Sizing orders")
    trades, post_gross_exposure, post_leverage = size_orders(
        prioritized, prices, current["CASH"], cfg
    )
    pre_gross_exposure = net_liq - current["CASH"]
    pre_leverage = pre_gross_exposure / net_liq if net_liq else 0.0
    pre_path = write_pre_trade_report(
        Path(cfg.io.report_dir),
        ts_dt,
        cfg.ibkr.account_id,
        drifts,
        trades,
        prices,
        pre_gross_exposure,
        pre_leverage,
        post_gross_exposure,
        post_leverage,
        cfg,
    )
    logging.info("Pre-trade report written to %s", pre_path)
    print("[blue]Rendering preview[/blue]")
    logging.info("Rendering preview")
    table = render_preview(
        prioritized,
        trades,
        pre_gross_exposure,
        pre_leverage,
        post_gross_exposure,
        post_leverage,
    )
    print(table)
    if args.dry_run:
        print("[green]Dry run complete (no orders submitted).[/green]")
        logging.info("Dry run complete (no orders submitted).")
        return

    if cfg.ibkr.read_only or args.read_only:
        print(
            "[yellow]Read-only mode: trading is disabled; no orders will be submitted.[/yellow]"
        )
        logging.info(
            "Read-only mode: trading is disabled; no orders will be submitted."
        )
        return

    if not args.yes:
        resp = input("Proceed? [y/N]: ").strip().lower()
        if resp != "y":
            print("[yellow]Aborted by user.[/yellow]")
            logging.info("Aborted by user.")
            return

    print("[blue]Submitting batch market orders[/blue]")
    logging.info("Submitting batch market orders")
    await client.connect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)
    try:
        results = await submit_batch(client, trades, cfg)
    finally:
        await client.disconnect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)

    for res in results:
        qty = res.get("fill_qty", res.get("filled", 0))
        price = res.get("fill_price", res.get("avg_fill_price", 0))
        print(
            f"[green]{res.get('symbol')}: {res.get('status')} "
            f"{qty} @ {price}[/green]"
        )
        logging.info(
            "%s: %s %s @ %s",
            res.get("symbol"),
            res.get("status"),
            qty,
            price,
        )
    if any(r.get("status") != "Filled" for r in results):
        logging.error("One or more orders failed to fill")
        raise SystemExit(1)

    cash_after = current["CASH"]
    positions = current.copy()
    prices_before = prices.copy()
    results_by_symbol = {r.get("symbol"): r for r in results}
    for trade in trades:
        res = results_by_symbol.get(trade.symbol, {})
        filled_any = res.get("fill_qty")
        if filled_any is None:
            filled_any = res.get("filled", trade.quantity)
        filled = float(filled_any)
        price_any = res.get("fill_price")
        if price_any is None:
            price_any = res.get("avg_fill_price", prices.get(trade.symbol, 0.0))
        price = float(price_any)
        if trade.action == "BUY":
            positions[trade.symbol] = positions.get(trade.symbol, 0.0) + filled
            cash_after -= filled * price
        else:
            positions[trade.symbol] = positions.get(trade.symbol, 0.0) - filled
            cash_after += filled * price
        prices[trade.symbol] = price

    post_gross_exposure_actual = net_liq - cash_after
    post_leverage_actual = post_gross_exposure_actual / net_liq if net_liq else 0.0
    post_path = write_post_trade_report(
        Path(cfg.io.report_dir),
        ts_dt,
        cfg.ibkr.account_id,
        drifts,
        trades,
        results,
        prices_before,
        pre_gross_exposure,
        pre_leverage,
        post_gross_exposure_actual,
        post_leverage_actual,
        cfg,
    )
    logging.info("Post-trade report written to %s", post_path)
    logging.info(
        "Rebalance complete: %d trades executed. Post leverage %.4f",
        len(trades),
        post_leverage_actual,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="IBKR ETF Rebalancer (scaffold)")
    parser.add_argument(
        "--config", default="config/settings.ini", help="Path to settings file"
    )
    parser.add_argument(
        "--csv", default="data/portfolios.csv", help="Path to portfolio CSV"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render preview and exit without prompting or submitting orders",
    )
    parser.add_argument(
        "--yes",
        "--no-confirm",
        action="store_true",
        dest="yes",
        help="Submit orders without prompting for confirmation",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Force read-only mode; block order submission",
    )
    args = parser.parse_args()

    try:
        asyncio.run(_run(args))
    except (ConfigError, PortfolioCSVError, IBKRError) as exc:
        logging.error(str(exc))
        print(f"[red]{exc}[/red]")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
