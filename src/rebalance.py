"""Rebalance CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rich import print

from src.broker.execution import submit_batch
from src.broker.ibkr_client import IBKRClient, IBKRError
from src.core.drift import compute_drift, prioritize_by_drift
from src.core.preview import render as render_preview
from src.core.pricing import PricingError, get_price
from src.core.sizing import size_orders
from src.io.config_loader import ConfigError, load_config
from src.io.portfolio_csv import PortfolioCSVError, load_portfolios


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

    print(f"[blue]Loading portfolios from {csv_path}[/blue]")
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
    await client.connect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)
    try:
        print("[blue]Retrieving account snapshot[/blue]")
        snapshot = await client.snapshot(cfg.ibkr.account_id)

        current = {p["symbol"]: float(p["position"]) for p in snapshot["positions"]}
        current["CASH"] = float(snapshot["cash"])

        symbols = set(current) | set(portfolios)
        symbols.discard("CASH")
        prices: dict[str, float] = {}

        print(f"[blue]Fetching prices for {len(symbols)} symbols[/blue]")
        # Use market prices for all symbols, including those already held, to
        # ensure consistent valuation across the portfolio.
        tasks = [
            asyncio.create_task(_fetch_price(client._ib, sym, cfg)) for sym in symbols
        ]
        for idx, task in enumerate(asyncio.as_completed(tasks), 1):
            try:
                symbol, price = await task
            except PricingError as exc:
                print(f"[red]{exc}[/red]")
                for t in tasks:
                    t.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                raise SystemExit(1)
            prices[symbol] = price
            print(f"[blue]  ({idx}/{len(symbols)}) {symbol}[/blue]")

        net_liq = snapshot["cash"] + sum(
            prices[sym] * qty for sym, qty in current.items() if sym != "CASH"
        )
    finally:
        await client.disconnect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)

    targets: dict[str, float] = {}
    for symbol, weights in portfolios.items():
        targets[symbol] = (
            weights["smurf"] * cfg.models.smurf
            + weights["badass"] * cfg.models.badass
            + weights["gltr"] * cfg.models.gltr
        )

    print("[blue]Computing drift[/blue]")
    drifts = compute_drift(current, targets, prices, net_liq, cfg)
    print("[blue]Prioritizing trades[/blue]")
    prioritized = prioritize_by_drift(drifts, cfg)
    print("[blue]Sizing orders[/blue]")
    trades, post_gross_exposure, post_leverage = size_orders(
        prioritized, prices, current["CASH"], cfg
    )
    pre_gross_exposure = net_liq - current["CASH"]
    pre_leverage = pre_gross_exposure / net_liq if net_liq else 0.0
    print("[blue]Rendering preview[/blue]")
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
        return

    if cfg.ibkr.read_only or args.read_only:
        print(
            "[yellow]Read-only mode: trading is disabled; no orders will be submitted.[/yellow]"
        )
        return

    if not args.yes:
        resp = input("Proceed? [y/N]: ").strip().lower()
        if resp != "y":
            print("[yellow]Aborted by user.[/yellow]")
            return

    print("[blue]Submitting batch market orders[/blue]")
    await client.connect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)
    try:
        results = await submit_batch(client, trades, cfg)
    finally:
        await client.disconnect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)

    for res in results:
        print(
            f"[green]{res.get('symbol')}: {res.get('status')} "
            f"{res.get('filled', 0)} @ {res.get('avg_fill_price', 0)}[/green]"
        )
    if any(r.get("status") != "Filled" for r in results):
        raise SystemExit(1)


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
        print(f"[red]{exc}[/red]")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
