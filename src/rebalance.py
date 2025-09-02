import argparse
from pathlib import Path

from rich import print


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
    cfg = Path(args.config)
    csv = Path(args.csv)
    print(f"[bold]Loaded[/bold] config: {cfg.resolve()}")
    print(f"[bold]Loaded[/bold] portfolios: {csv.resolve()}")
    print(
        "[cyan]Preview would be generated here (drift %, drift $, sizing, leverage).[/cyan]"
    )
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
