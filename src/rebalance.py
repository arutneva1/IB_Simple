import argparse
from pathlib import Path
from types import SimpleNamespace

from rich import print

from src.core.drift import compute_drift, prioritize_by_drift
from src.core.preview import render as render_preview


def main():
    parser = argparse.ArgumentParser(description="IBKR ETF Rebalancer (scaffold)")
    parser.add_argument("--config", default="config/settings.ini")
    parser.add_argument("--csv", default="data/portfolios.csv")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    parser.add_argument("--read-only", action="store_true")
    args = parser.parse_args()

    if args.read_only and args.confirm:
        print("[yellow]Read-only is enabled; trading will be blocked.[/yellow]")

    # Placeholder flow
    cfg_path = Path(args.config)
    csv_path = Path(args.csv)
    print(f"[bold]Loaded[/bold] config: {cfg_path.resolve()}")
    print(f"[bold]Loaded[/bold] portfolios: {csv_path.resolve()}")

    # Placeholder portfolio data
    cfg = SimpleNamespace(rebalance=SimpleNamespace(min_order_usd=100))
    current = {"AAA": 10, "BBB": 5, "CASH": 5000}
    targets = {"AAA": 50.0, "BBB": 50.0}
    prices = {"AAA": 100.0, "BBB": 80.0}
    net_liq = 10 * 100.0 + 5 * 80.0 + 5000

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
        print(
            "[yellow]No --confirm provided; exiting after preview placeholder.[/yellow]"
        )


if __name__ == "__main__":
    main()
