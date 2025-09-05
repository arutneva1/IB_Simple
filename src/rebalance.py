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
from src.core.confirmation import confirm_global, confirm_per_account
from src.core.drift import compute_drift, prioritize_by_drift
from src.core.errors import PlanningError
from src.core.planner import Plan, _fetch_price, plan_account
from src.core.preview import render as render_preview
from src.core.sizing import size_orders
from src.io import (
    AppConfig,
    ConfigError,
    ConfirmMode,
    load_config,
    merge_account_overrides,
)
from src.io.portfolio_csv import PortfolioCSVError
from src.io.portfolio_csv import load_portfolios_map as load_portfolios
from src.io.reporting import (
    append_run_summary,
    setup_logging,
    write_post_trade_report,
    write_pre_trade_report,
)


async def _print_err(msg: str, lock: asyncio.Lock | None) -> None:
    """Print ``msg`` using ``rich.print`` with optional ``asyncio.Lock``."""
    if lock is not None:
        async with lock:
            print(msg)
    else:
        print(msg)


async def _run(args: argparse.Namespace) -> list[tuple[str, str]]:
    cfg_path = Path(args.config)
    csv_arg = args.csv
    print(f"[blue]Loading configuration from {cfg_path}[/blue]")
    cfg: AppConfig = load_config(cfg_path)
    cfg_path = cfg_path.resolve()
    cfg_dir = cfg_path.parent
    cli_confirm_mode = getattr(args, "confirm_mode", None)
    if cli_confirm_mode:
        cfg.accounts.confirm_mode = ConfirmMode(cli_confirm_mode)
    if getattr(args, "parallel_accounts", False):
        cfg.accounts.parallel = True
    ts_dt = datetime.now(timezone.utc)
    timestamp = ts_dt.strftime("%Y%m%dT%H%M%S")
    setup_logging(Path(cfg.io.report_dir), cfg.io.log_level, timestamp)
    logging.info("Loaded configuration from %s", cfg_path)

    if csv_arg is not None:
        csv_path = Path(csv_arg)
    else:
        accounts_path = getattr(cfg.accounts, "path", None)
        if accounts_path is not None:
            csv_path = accounts_path
        else:
            csv_path = Path("data/portfolios.csv")
    if not csv_path.is_absolute():
        csv_path = (cfg_dir / csv_path).resolve()
    portfolio_paths: dict[str, Path] = getattr(cfg, "portfolio_paths", {})
    path_map: dict[str, Path] = {}
    for acct in cfg.accounts.ids:
        p = portfolio_paths.get(acct, csv_path)
        if not p.is_absolute():
            p = (cfg_dir / p).resolve()
        path_map[acct] = p
    print("[blue]Loading portfolios[/blue]")
    for acct, p in path_map.items():
        logging.info("Portfolio for %s loaded from %s", acct, p)
    portfolios_by_account = await load_portfolios(
        path_map,
        host=cfg.ibkr.host,
        port=cfg.ibkr.port,
        client_id=cfg.ibkr.client_id,
    )
    failures: list[tuple[str, str]] = []
    summary_rows: list[dict[str, object]] = []

    def capture_summary(_: Path, __: datetime, row: dict[str, object]) -> None:
        summary_rows.append(row)

    accounts = cfg.accounts
    confirm_mode = getattr(accounts, "confirm_mode", ConfirmMode.PER_ACCOUNT)

    output_lock: asyncio.Lock | None = None
    if getattr(accounts, "parallel", False):
        output_lock = asyncio.Lock()

    async def handle_account(account_id: str) -> Plan | None:
        plan: Plan | None = None
        try:
            cfg_acct = merge_account_overrides(cfg, account_id)
            portfolios = portfolios_by_account[account_id]
            plan = await plan_account(
                account_id,
                portfolios,
                cfg_acct,
                ts_dt,
                client_factory=IBKRClient,
                compute_drift=compute_drift,
                prioritize_by_drift=prioritize_by_drift,
                size_orders=size_orders,
                fetch_price=_fetch_price,
                render_preview=render_preview,
                write_pre_trade_report=write_pre_trade_report,
                output_lock=output_lock,
            )
            if confirm_mode is ConfirmMode.PER_ACCOUNT and not (
                getattr(accounts, "parallel", False) and not args.yes
            ):
                await confirm_per_account(
                    plan,
                    args,
                    cfg,
                    ts_dt,
                    client_factory=IBKRClient,
                    submit_batch=submit_batch,
                    append_run_summary=capture_summary,
                    write_post_trade_report=write_post_trade_report,
                    compute_drift=compute_drift,
                    prioritize_by_drift=prioritize_by_drift,
                    size_orders=size_orders,
                    output_lock=output_lock,
                )
                return None
            return plan
        except (ConfigError, IBKRError, PlanningError) as exc:
            logging.error("Error processing account %s: %s", account_id, exc)
            await _print_err(f"[red]{exc}[/red]", output_lock)
            failures.append((account_id, str(exc)))
            planned_orders = plan["planned_orders"] if plan else 0
            buy_usd = plan["buy_usd"] if plan else 0.0
            sell_usd = plan["sell_usd"] if plan else 0.0
            pre_leverage = plan["pre_leverage"] if plan else 0.0
            capture_summary(
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
            return None
        except Exception as exc:  # noqa: BLE001
            logging.exception("Unhandled error processing account %s", account_id)
            await _print_err(f"[red]{exc}[/red]", output_lock)
            failures.append((account_id, str(exc)))
            planned_orders = plan["planned_orders"] if plan else 0
            buy_usd = plan["buy_usd"] if plan else 0.0
            sell_usd = plan["sell_usd"] if plan else 0.0
            pre_leverage = plan["pre_leverage"] if plan else 0.0
            capture_summary(
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
            return None

    plans: list[Plan] = []
    if getattr(accounts, "parallel", False):
        tasks: list[asyncio.Task] = []
        task_accounts: list[str] = []
        pacing = getattr(accounts, "pacing_sec", 0.0)

        async def start_after_delay(aid: str, delay: float) -> Plan | None:
            if delay:
                await asyncio.sleep(delay)
            return await handle_account(aid)

        for idx, account_id in enumerate(accounts.ids):
            tasks.append(
                asyncio.create_task(start_after_delay(account_id, idx * pacing))
            )
            task_accounts.append(account_id)
        results: list[Plan | Exception | None] = await asyncio.gather(
            *tasks, return_exceptions=True
        )
        for aid, res in zip(task_accounts, results):
            if isinstance(res, Exception):
                logging.error(
                    "Unhandled error processing account %s", aid, exc_info=res
                )
                await _print_err(f"[red]{res}[/red]", output_lock)
                failures.append((aid, str(res)))
                capture_summary(
                    Path(cfg.io.report_dir),
                    ts_dt,
                    {
                        "timestamp_run": ts_dt.isoformat(),
                        "account_id": aid,
                        "planned_orders": 0,
                        "submitted": 0,
                        "filled": 0,
                        "rejected": 0,
                        "buy_usd": 0.0,
                        "sell_usd": 0.0,
                        "pre_leverage": 0.0,
                        "post_leverage": 0.0,
                        "status": "failed",
                        "error": str(res),
                    },
                )
            elif res is not None:
                plans.append(res)
    else:
        pacing = getattr(accounts, "pacing_sec", 0)
        for idx, account_id in enumerate(accounts.ids):
            plan = await handle_account(account_id)
            if plan is not None:
                plans.append(plan)
            if idx < len(accounts.ids) - 1:
                await asyncio.sleep(pacing)

    if (
        getattr(accounts, "parallel", False)
        and confirm_mode is ConfirmMode.PER_ACCOUNT
        and not args.yes
    ):
        pacing = getattr(accounts, "pacing_sec", 0)
        for idx, plan in enumerate(plans):
            account_id = plan["account_id"]
            try:
                await confirm_per_account(
                    plan,
                    args,
                    cfg,
                    ts_dt,
                    client_factory=IBKRClient,
                    submit_batch=submit_batch,
                    append_run_summary=capture_summary,
                    write_post_trade_report=write_post_trade_report,
                    compute_drift=compute_drift,
                    prioritize_by_drift=prioritize_by_drift,
                    size_orders=size_orders,
                    output_lock=output_lock,
                )
            except (ConfigError, IBKRError, PlanningError) as exc:
                logging.error("Error processing account %s: %s", account_id, exc)
                await _print_err(f"[red]{exc}[/red]", output_lock)
                failures.append((account_id, str(exc)))
                capture_summary(
                    Path(cfg.io.report_dir),
                    ts_dt,
                    {
                        "timestamp_run": ts_dt.isoformat(),
                        "account_id": account_id,
                        "planned_orders": plan["planned_orders"],
                        "submitted": 0,
                        "filled": 0,
                        "rejected": 0,
                        "buy_usd": plan["buy_usd"],
                        "sell_usd": plan["sell_usd"],
                        "pre_leverage": plan["pre_leverage"],
                        "post_leverage": plan["pre_leverage"],
                        "status": "failed",
                        "error": str(exc),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                logging.exception(
                    "Unexpected error processing account %s: %s", account_id, exc
                )
                await _print_err(f"[red]{exc}[/red]", output_lock)
                failures.append((account_id, str(exc)))
                capture_summary(
                    Path(cfg.io.report_dir),
                    ts_dt,
                    {
                        "timestamp_run": ts_dt.isoformat(),
                        "account_id": account_id,
                        "planned_orders": plan["planned_orders"],
                        "submitted": 0,
                        "filled": 0,
                        "rejected": 0,
                        "buy_usd": plan["buy_usd"],
                        "sell_usd": plan["sell_usd"],
                        "pre_leverage": plan["pre_leverage"],
                        "post_leverage": plan["pre_leverage"],
                        "status": "failed",
                        "error": str(exc),
                    },
                )
            finally:
                if idx < len(plans) - 1:
                    await asyncio.sleep(pacing)

    if confirm_mode is ConfirmMode.GLOBAL:
        plans.sort(key=lambda p: str(p["account_id"]))
        failures.extend(
            await confirm_global(
                plans,
                args,
                cfg,
                ts_dt,
                client_factory=IBKRClient,
                submit_batch=submit_batch,
                append_run_summary=capture_summary,
                write_post_trade_report=write_post_trade_report,
                compute_drift=compute_drift,
                prioritize_by_drift=prioritize_by_drift,
                size_orders=size_orders,
                pacing_sec=getattr(accounts, "pacing_sec", 0),
                parallel_accounts=getattr(accounts, "parallel", False),
            )
        )

    summary_rows.sort(key=lambda r: str(r.get("account_id", "")))
    for row in summary_rows:
        append_run_summary(Path(cfg.io.report_dir), ts_dt, row)

    if failures:
        await _print_err("[red]One or more accounts failed:[/red]", output_lock)
        for acct, msg in failures:
            await _print_err(f"[red]- {acct}: {msg}[/red]", output_lock)
    return failures


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="IBKR ETF Rebalancer (scaffold)")
    parser.add_argument(
        "--config",
        default="config/settings.ini",
        help="Path to settings file",
    )
    parser.add_argument(
        "--csv",
        default=None,
        help="Path to portfolio CSV (defaults to [accounts] path or data/portfolios.csv)",
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
        choices=[mode.value for mode in ConfirmMode],
        help="Confirmation mode: per-account or global",
    )
    parser.add_argument(
        "--parallel-accounts",
        action="store_true",
        help=(
            "Plan and execute accounts concurrently; prompts remain serialized "
            "without --yes"
        ),
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
