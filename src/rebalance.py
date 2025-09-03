"""Rebalance CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from rich import print

from src.broker.ibkr_client import IBKRClient, IBKRError
from src.core.drift import compute_drift, prioritize_by_drift
from src.core.preview import render as render_preview
from src.io.config_loader import ConfigError, load_config
from src.io.portfolio_csv import PortfolioCSVError, load_portfolios


async def _run(args: argparse.Namespace) -> None:
    cfg_path = Path(args.config)
    csv_path = Path(args.csv)

    cfg = load_config(cfg_path)
    portfolios = await load_portfolios(
        csv_path,
        host=cfg.ibkr.host,
        port=cfg.ibkr.port,
        client_id=cfg.ibkr.client_id,
    )

    client = IBKRClient()
    await client.connect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)
    try:
        snapshot = await client.snapshot(cfg.ibkr.account_id)
    finally:
        await client.disconnect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)

    current = {p["symbol"]: float(p["position"]) for p in snapshot["positions"]}
    current["CASH"] = float(snapshot["cash"])
    prices = {p["symbol"]: float(p["avg_cost"]) for p in snapshot["positions"]}
    net_liq = snapshot["cash"] + sum(
        prices[sym] * qty for sym, qty in current.items() if sym != "CASH"
    )

    targets: dict[str, float] = {}
    for symbol, weights in portfolios.items():
        targets[symbol] = (
            weights["smurf"] * cfg.models.smurf
            + weights["badass"] * cfg.models.badass
            + weights["gltr"] * cfg.models.gltr
        )

    drifts = compute_drift(current, targets, prices, net_liq, cfg)
    prioritized = prioritize_by_drift(drifts, cfg)
    table = render_preview(prioritized)
    print(table)
    if args.dry_run:
        print("[green]Dry run complete (no orders submitted).[/green]")
        return
    if args.confirm:
        resp = input("Proceed? [y/N]: ").strip().lower()
        if resp == "y":
            print("[green]Submitting batch market orders (placeholder)...[/green]")
            print(
                "[green]Done. Report would be written to reports/ (placeholder).[/green]"
            )
        else:
            print("[yellow]Aborted by user.[/yellow]")
    else:
        print("[yellow]No --confirm provided; exiting after preview.[/yellow]")


def main() -> None:
    parser = argparse.ArgumentParser(description="IBKR ETF Rebalancer (scaffold)")
    parser.add_argument("--config", default="config/settings.ini")
    parser.add_argument("--csv", default="data/portfolios.csv")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--read-only", action="store_true")
    args = parser.parse_args()

    if args.read_only and args.confirm:
        print("[yellow]Read-only is enabled; trading will be blocked.[/yellow]")

    try:
        asyncio.run(_run(args))
    except (ConfigError, PortfolioCSVError, IBKRError) as exc:
        print(f"[red]{exc}[/red]")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
