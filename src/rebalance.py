"""Rebalance CLI entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from rich import print

from src.broker.errors import IBKRError
from src.broker.execution import submit_batch
from src.broker.ibkr_client import IBKRClient
from src.core.drift import compute_drift, prioritize_by_drift
from src.core.errors import PlanningError
from src.core.preview import render as render_preview
from src.core.sizing import size_orders
from src.io import AppConfig, ConfigError, load_config
from src.io.portfolio_csv import PortfolioCSVError, load_portfolios
from src.io.reporting import (
    append_run_summary,
    setup_logging,
    write_post_trade_report,
    write_pre_trade_report,
)
from src.core.planner import Plan, plan_account, _fetch_price
from src.core.confirmation import confirm_per_account, confirm_global


async def _run(args: argparse.Namespace) -> list[tuple[str, str]]:
    cfg_path = Path(args.config)
    csv_path = Path(args.csv)
    print(f"[blue]Loading configuration from {cfg_path}[/blue]")
    cfg: AppConfig = load_config(cfg_path)
    cli_confirm_mode = getattr(args, "confirm_mode", None)
    if cli_confirm_mode and cfg.accounts is not None:
        cfg.accounts.confirm_mode = cli_confirm_mode
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
    failures: list[tuple[str, str]] = []

    accounts = cfg.accounts
    assert accounts is not None
    confirm_mode = getattr(accounts, "confirm_mode", "per_account")
    plans: list[Plan] = []
    for account_id in accounts.ids:
        plan: Plan | None = None
        try:
            plan = await plan_account(
                account_id,
                portfolios,
                cfg,
                ts_dt,
                client_factory=IBKRClient,
                compute_drift=compute_drift,
                prioritize_by_drift=prioritize_by_drift,
                size_orders=size_orders,
                fetch_price=_fetch_price,
                render_preview=render_preview,
                write_pre_trade_report=write_pre_trade_report,
            )
            if confirm_mode == "per_account":
                await confirm_per_account(
                    plan,
                    args,
                    cfg,
                    ts_dt,
                    client_factory=IBKRClient,
                    submit_batch=submit_batch,
                    append_run_summary=append_run_summary,
                    write_post_trade_report=write_post_trade_report,
                    compute_drift=compute_drift,
                    prioritize_by_drift=prioritize_by_drift,
                    size_orders=size_orders,
                )
            else:
                plans.append(plan)
        except (ConfigError, IBKRError, PlanningError) as exc:
            logging.error("Error processing account %s: %s", account_id, exc)
            print(f"[red]{exc}[/red]")
            failures.append((account_id, str(exc)))
            planned_orders = plan["planned_orders"] if plan else 0
            buy_usd = plan["buy_usd"] if plan else 0.0
            sell_usd = plan["sell_usd"] if plan else 0.0
            pre_leverage = plan["pre_leverage"] if plan else 0.0
            append_run_summary(
                Path(cfg.io.report_dir),
                ts_dt,
                {
                    "timestamp_run": ts_dt.isoformat(),
                    "account_id": account_id,
                    "planned_orders": planned_orders,
                    "submitted": 0,
                    "filled": 0,
                    "rejected": 0,
                    "buy_usd": buy_usd,
                    "sell_usd": sell_usd,
                    "pre_leverage": pre_leverage,
                    "post_leverage": pre_leverage,
                    "status": "failed",
                    "error": str(exc),
                },
            )
        finally:
            await asyncio.sleep(getattr(accounts, "pacing_sec", 0))

    if confirm_mode == "global":
        failures.extend(
            await confirm_global(
                plans,
                args,
                cfg,
                ts_dt,
                client_factory=IBKRClient,
                submit_batch=submit_batch,
                append_run_summary=append_run_summary,
                write_post_trade_report=write_post_trade_report,
                compute_drift=compute_drift,
                prioritize_by_drift=prioritize_by_drift,
                size_orders=size_orders,
                pacing_sec=getattr(accounts, "pacing_sec", 0),
            )
        )

    if failures:
        print("[red]One or more accounts failed:[/red]")
        for acct, msg in failures:
            print(f"[red]- {acct}: {msg}[/red]")
    return failures


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="IBKR ETF Rebalancer (scaffold)")
    parser.add_argument(
        "--config", default="config/settings.ini", help="Path to settings file",
    )
    parser.add_argument(
        "--csv", default="data/portfolios.csv", help="Path to portfolio CSV",
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
    parser.add_argument(
        "--confirm-mode",
        choices=["per_account", "global"],
        help="Confirmation mode: per-account or global",
    )
    args = parser.parse_args(argv if argv is not None else [])

    try:
        failures = asyncio.run(_run(args))
        if failures:
            raise SystemExit(1)
    except KeyboardInterrupt:
        logging.info("Aborted by user via keyboard interrupt")
        print("[yellow]Aborted by user.[/yellow]")
        raise SystemExit(1)
    except (ConfigError, PortfolioCSVError, IBKRError, PlanningError) as exc:
        logging.error(str(exc))
        print(f"[red]{exc}[/red]")
        raise SystemExit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
