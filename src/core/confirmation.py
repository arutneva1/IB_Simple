from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping, cast

from rich import print

from src.broker.errors import IBKRError
from src.broker.ibkr_client import IBKRClient
from src.core.errors import PlanningError
from src.core.planner import Plan
from src.io import AppConfig, ConfigError, merge_account_overrides


async def _prompt_user(prompt: str) -> str:
    """Prompt the user without blocking the event loop."""
    return await asyncio.to_thread(input, prompt)


async def confirm_per_account(
    plan: Plan,
    args: Any,
    cfg: AppConfig,
    ts_dt: datetime,
    *,
    client_factory: type[IBKRClient],
    submit_batch,
    append_run_summary,
    write_post_trade_report,
    compute_drift,
    prioritize_by_drift,
    size_orders,
    output_lock: asyncio.Lock | None = None,
) -> None:
    """Handle confirmation, execution, and reporting for a single account."""
    cfg = merge_account_overrides(cfg, plan["account_id"])

    account_id = plan["account_id"]
    trades = plan["trades"]
    drifts = plan["drifts"]
    prices = plan["prices"]
    current = plan["current"]
    targets = plan["targets"]
    net_liq = plan["net_liq"]
    pre_gross_exposure = plan["pre_gross_exposure"]
    pre_leverage = plan["pre_leverage"]
    post_leverage = plan["post_leverage"]
    table = plan["table"]
    planned_orders = plan["planned_orders"]
    planned_orders_total = planned_orders
    buy_usd = plan["buy_usd"]
    sell_usd = plan["sell_usd"]
    buy_usd_actual = 0.0
    sell_usd_actual = 0.0

    async def _print(*args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        if output_lock is not None:
            async with output_lock:
                print(*args, **kwargs)
        else:
            print(*args, **kwargs)

    async def _append(row: Mapping[str, Any]) -> None:
        if output_lock is not None:
            async with output_lock:
                append_run_summary(Path(cfg.io.report_dir), ts_dt, row)
        else:
            append_run_summary(Path(cfg.io.report_dir), ts_dt, row)

    def _build_lookup(
        res_list: list[Mapping[str, Any]],
    ) -> dict[tuple[str | None, str | None], deque[Mapping[str, Any]]]:
        lookup: dict[tuple[str | None, str | None], deque[Mapping[str, Any]]] = (
            defaultdict(deque)
        )
        for r in res_list:
            sym = r.get("symbol")
            if sym is None:
                continue
            act = r.get("action")
            lookup[(sym, act)].append(r)
        return lookup

    def _totals(tr_list, res_list) -> tuple[float, float]:
        lookup = _build_lookup(res_list)
        buy_total = 0.0
        sell_total = 0.0
        for t in tr_list:
            q = lookup.get((t.symbol, t.action))
            res = q.popleft() if q else {}
            if not res:
                continue
            qty_any = res.get("fill_qty")
            if qty_any is None:
                qty_any = res.get("filled", 0.0)
            price_any = res.get("fill_price")
            if price_any is None:
                price_any = res.get("avg_fill_price", 0.0)
            qty = float(qty_any or 0.0)
            price = float(price_any or 0.0)
            value = qty * price
            if t.action == "BUY":
                buy_total += value
            else:
                sell_total += value
        return buy_total, sell_total

    def _apply_fills(tr_list, res_list, positions, prices, cash):
        lookup = _build_lookup(res_list)
        buy_total = 0.0
        sell_total = 0.0
        for t in tr_list:
            q = lookup.get((t.symbol, t.action))
            res = q.popleft() if q else {}
            if not res:
                raise IBKRError(f"Missing fill result for {t.symbol} {t.action}")
            qty_any = res.get("fill_qty")
            if qty_any is None:
                qty_any = res.get("filled")
            if qty_any is None:
                raise IBKRError(f"Missing fill quantity for {t.symbol} {t.action}")
            filled = float(qty_any)
            price_any = res.get("fill_price")
            if price_any is None:
                price_any = res.get("avg_fill_price")
            if price_any is None:
                prior = prices.get(t.symbol)
                if prior is None or prior <= 0:
                    raise IBKRError(f"Missing fill price for {t.symbol}")
                price = float(prior)
            else:
                price = float(price_any)
            if price <= 0:
                prior = prices.get(t.symbol)
                if prior is None or prior <= 0:
                    raise IBKRError(f"Missing fill price for {t.symbol}")
                price = float(prior)
            value = filled * price
            if t.action == "BUY":
                positions[t.symbol] = positions.get(t.symbol, 0.0) + filled
                cash -= value
                buy_total += value
            else:
                positions[t.symbol] = positions.get(t.symbol, 0.0) - filled
                cash += value
                sell_total += value
            prices[t.symbol] = price
        positions["CASH"] = cash
        return buy_total, sell_total, cash

    await _print(table)
    if args.dry_run:
        await _print("[green]Dry run complete (no orders submitted).[/green]")
        logging.info("Dry run complete (no orders submitted).")
        await _append(
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
                "post_leverage": post_leverage,
                "status": "dry_run",
                "error": "",
            }
        )
        return

    if cfg.ibkr.read_only or args.read_only:
        await _print(
            "[yellow]Read-only mode: trading is disabled; no orders will be submitted.[/yellow]"
        )
        logging.info(
            "Read-only mode: trading is disabled; no orders will be submitted."
        )
        await _append(
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
                "status": "read_only",
                "error": "",
            }
        )
        return

    if not args.yes:
        resp = (await _prompt_user("Proceed? [y/N]: ")).strip().lower()
        if resp != "y":
            await _print("[yellow]Aborted by user.[/yellow]")
            logging.info("Aborted by user.")
            await _append(
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
                    "status": "aborted",
                    "error": "",
                }
            )
            return

    await _print("[blue]Submitting batch market orders[/blue]")
    logging.info("Submitting batch market orders for %s", account_id)
    client = client_factory()
    if hasattr(client, "__aenter__"):
        setattr(client, "_host", cfg.ibkr.host)
        setattr(client, "_port", cfg.ibkr.port)
        setattr(client, "_client_id", cfg.ibkr.client_id)
        async with client:
            results = await submit_batch(client, trades, cfg, account_id)
    else:
        await client.connect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)
        try:
            results = await submit_batch(client, trades, cfg, account_id)
        finally:
            await client.disconnect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)

    for res in results:
        qty = res.get("fill_qty", res.get("filled", 0))
        price = res.get("fill_price", res.get("avg_fill_price", 0))
        await _print(
            f"[green]{res.get('symbol')}: {res.get('status')} {qty} @ {price}[/green]"
        )
        logging.info("%s: %s %s @ %s", res.get("symbol"), res.get("status"), qty, price)
    if any(r.get("status") != "Filled" for r in results):
        logging.error("One or more orders failed to fill")
        filled = sum(1 for r in results if r.get("status") == "Filled")
        rejected = len(results) - filled
        buy_usd_actual, sell_usd_actual = _totals(trades, results)
        cash_after = current["CASH"] - buy_usd_actual + sell_usd_actual
        post_leverage_actual = (net_liq - cash_after) / net_liq if net_liq else 0.0
        await _append(
            {
                "timestamp_run": ts_dt.isoformat(),
                "account_id": account_id,
                "planned_orders": planned_orders,
                "submitted": len(trades),
                "filled": filled,
                "rejected": rejected,
                "buy_usd": buy_usd_actual,
                "sell_usd": sell_usd_actual,
                "pre_leverage": pre_leverage,
                "post_leverage": post_leverage_actual,
                "status": "failed",
                "error": "One or more orders failed to fill",
            }
        )
        raise IBKRError("One or more orders failed to fill")

    cash_after = current["CASH"]
    positions = current.copy()
    prices_before = prices.copy()
    try:
        buy_pass, sell_pass, cash_after = _apply_fills(
            trades, results, positions, prices, cash_after
        )
    except IBKRError as exc:
        logging.error("%s", exc)
        filled = sum(1 for r in results if r.get("status") == "Filled")
        rejected = len(results) - filled
        buy_usd_actual, sell_usd_actual = _totals(trades, results)
        cash_after = current["CASH"] - buy_usd_actual + sell_usd_actual
        post_leverage_actual = (net_liq - cash_after) / net_liq if net_liq else 0.0
        await _append(
            {
                "timestamp_run": ts_dt.isoformat(),
                "account_id": account_id,
                "planned_orders": planned_orders,
                "submitted": len(results),
                "filled": filled,
                "rejected": rejected,
                "buy_usd": buy_usd_actual,
                "sell_usd": sell_usd_actual,
                "pre_leverage": pre_leverage,
                "post_leverage": post_leverage_actual,
                "status": "failed",
                "error": str(exc),
            }
        )
        raise
    buy_usd_actual += buy_pass
    sell_usd_actual += sell_pass

    all_trades = list(trades)
    all_results = list(results)
    max_passes = getattr(cfg.rebalance, "max_passes", 1)
    passes = 1
    while passes < max_passes:
        buffer_type = getattr(cfg.rebalance, "cash_buffer_type", "pct")
        if buffer_type == "pct":
            reserve = net_liq * getattr(cfg.rebalance, "cash_buffer_pct", 0.0)
        else:
            reserve = getattr(cfg.rebalance, "cash_buffer_abs", 0.0)
        available_cash = cash_after - reserve
        if available_cash < cfg.rebalance.min_order_usd:
            break
        iter_drifts = compute_drift(
            account_id, positions, targets, prices, net_liq, cfg
        )
        iter_prioritized = prioritize_by_drift(account_id, iter_drifts, cfg)
        extra_trades, _, _ = size_orders(
            account_id, iter_prioritized, prices, positions, cash_after, net_liq, cfg
        )
        if not extra_trades:
            break
        planned_orders_total += len(extra_trades)
        await _print(
            f"[blue]Submitting additional batch market orders (pass {passes + 1})[/blue]"
        )
        logging.info(
            "Submitting batch market orders for %s (pass %d)", account_id, passes + 1
        )
        client = client_factory()
        if hasattr(client, "__aenter__"):
            setattr(client, "_host", cfg.ibkr.host)
            setattr(client, "_port", cfg.ibkr.port)
            setattr(client, "_client_id", cfg.ibkr.client_id)
            async with client:
                extra_results = await submit_batch(
                    client, extra_trades, cfg, account_id
                )
        else:
            await client.connect(cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id)
            try:
                extra_results = await submit_batch(
                    client, extra_trades, cfg, account_id
                )
            finally:
                await client.disconnect(
                    cfg.ibkr.host, cfg.ibkr.port, cfg.ibkr.client_id
                )
        for res in extra_results:
            qty = res.get("fill_qty", res.get("filled", 0))
            price = res.get("fill_price", res.get("avg_fill_price", 0))
            await _print(
                f"[green]{res.get('symbol')}: {res.get('status')} {qty} @ {price}[/green]"
            )
            logging.info(
                "%s: %s %s @ %s", res.get("symbol"), res.get("status"), qty, price
            )
        if any(r.get("status") != "Filled" for r in extra_results):
            logging.error("One or more orders failed to fill")
            extra_buy, extra_sell = _totals(extra_trades, extra_results)
            buy_usd_actual += extra_buy
            sell_usd_actual += extra_sell
            cash_after = current["CASH"] - buy_usd_actual + sell_usd_actual
            current_trades = all_trades + list(extra_trades)
            current_results = all_results + list(extra_results)
            filled = sum(1 for r in current_results if r.get("status") == "Filled")
            rejected = len(current_results) - filled
            post_leverage_actual = (net_liq - cash_after) / net_liq if net_liq else 0.0
            await _append(
                {
                    "timestamp_run": ts_dt.isoformat(),
                    "account_id": account_id,
                    "planned_orders": len(current_trades),
                    "submitted": len(current_results),
                    "filled": filled,
                    "rejected": rejected,
                    "buy_usd": buy_usd_actual,
                    "sell_usd": sell_usd_actual,
                    "pre_leverage": pre_leverage,
                    "post_leverage": post_leverage_actual,
                    "status": "failed",
                    "error": "One or more orders failed to fill",
                }
            )
            raise IBKRError("One or more orders failed to fill")
        try:
            buy_pass, sell_pass, cash_after = _apply_fills(
                extra_trades, extra_results, positions, prices, cash_after
            )
        except IBKRError as exc:
            logging.error("%s", exc)
            extra_buy, extra_sell = _totals(extra_trades, extra_results)
            buy_usd_actual += extra_buy
            sell_usd_actual += extra_sell
            cash_after = current["CASH"] - buy_usd_actual + sell_usd_actual
            current_trades = all_trades + list(extra_trades)
            current_results = all_results + list(extra_results)
            filled = sum(1 for r in current_results if r.get("status") == "Filled")
            rejected = len(current_results) - filled
            post_leverage_actual = (net_liq - cash_after) / net_liq if net_liq else 0.0
            await _append(
                {
                    "timestamp_run": ts_dt.isoformat(),
                    "account_id": account_id,
                    "planned_orders": len(current_trades),
                    "submitted": len(current_results),
                    "filled": filled,
                    "rejected": rejected,
                    "buy_usd": buy_usd_actual,
                    "sell_usd": sell_usd_actual,
                    "pre_leverage": pre_leverage,
                    "post_leverage": post_leverage_actual,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            raise
        buy_usd_actual += buy_pass
        sell_usd_actual += sell_pass
        all_trades.extend(extra_trades)
        all_results.extend(extra_results)
        passes += 1

    post_gross_exposure_actual = net_liq - cash_after
    post_leverage_actual = post_gross_exposure_actual / net_liq if net_liq else 0.0
    filled = sum(1 for r in all_results if r.get("status") == "Filled")
    rejected = len(all_results) - filled
    buy_usd = buy_usd_actual
    sell_usd = sell_usd_actual
    trades = all_trades
    results = all_results
    post_path = write_post_trade_report(
        Path(cfg.io.report_dir),
        ts_dt,
        account_id,
        drifts,
        trades,
        results,
        prices_before,
        net_liq,
        pre_gross_exposure,
        pre_leverage,
        post_gross_exposure_actual,
        post_leverage_actual,
        cfg,
    )
    logging.info("Post-trade report for %s written to %s", account_id, post_path)
    logging.info(
        "Rebalance complete for %s: %d trades executed. Post leverage %.4f",
        account_id,
        len(trades),
        post_leverage_actual,
    )
    await _append(
        {
            "timestamp_run": ts_dt.isoformat(),
            "account_id": account_id,
            "planned_orders": planned_orders_total,
            "submitted": len(trades),
            "filled": filled,
            "rejected": rejected,
            "buy_usd": buy_usd,
            "sell_usd": sell_usd,
            "pre_leverage": pre_leverage,
            "post_leverage": post_leverage_actual,
            "status": "completed",
            "error": "",
        }
    )


async def confirm_global(
    plans: list[Plan],
    args: Any,
    cfg: AppConfig,
    ts_dt: datetime,
    *,
    client_factory: type[IBKRClient],
    submit_batch,
    append_run_summary,
    write_post_trade_report,
    compute_drift,
    prioritize_by_drift,
    size_orders,
    pacing_sec: float = 0.0,
    parallel_accounts: bool = True,
) -> list[tuple[str, str]]:
    """Handle global confirmation workflow for multiple accounts."""

    args = SimpleNamespace(**vars(args))

    for plan in plans:
        print(plan["table"])

    failures: list[tuple[str, str]] = []

    if args.dry_run:
        print("[green]Dry run complete (no orders submitted).[/green]")
        logging.info("Dry run complete (no orders submitted).")
        for plan in plans:
            buy_usd = sum(t.notional for t in plan["trades"] if t.action == "BUY")
            sell_usd = sum(t.notional for t in plan["trades"] if t.action == "SELL")
            append_run_summary(
                Path(cfg.io.report_dir),
                ts_dt,
                {
                    "timestamp_run": ts_dt.isoformat(),
                    "account_id": plan["account_id"],
                    "planned_orders": len(plan["trades"]),
                    "submitted": 0,
                    "filled": 0,
                    "rejected": 0,
                    "buy_usd": buy_usd,
                    "sell_usd": sell_usd,
                    "pre_leverage": plan["pre_leverage"],
                    "post_leverage": plan["post_leverage"],
                    "status": "dry_run",
                    "error": "",
                },
            )
        return failures

    if cfg.ibkr.read_only or args.read_only:
        print(
            "[yellow]Read-only mode: trading is disabled; no orders will be submitted.[/yellow]"
        )
        logging.info(
            "Read-only mode: trading is disabled; no orders will be submitted."
        )
        for plan in plans:
            buy_usd = sum(t.notional for t in plan["trades"] if t.action == "BUY")
            sell_usd = sum(t.notional for t in plan["trades"] if t.action == "SELL")
            append_run_summary(
                Path(cfg.io.report_dir),
                ts_dt,
                {
                    "timestamp_run": ts_dt.isoformat(),
                    "account_id": plan["account_id"],
                    "planned_orders": len(plan["trades"]),
                    "submitted": 0,
                    "filled": 0,
                    "rejected": 0,
                    "buy_usd": buy_usd,
                    "sell_usd": sell_usd,
                    "pre_leverage": plan["pre_leverage"],
                    "post_leverage": plan["pre_leverage"],
                    "status": "read_only",
                    "error": "",
                },
            )
        return failures

    if not args.yes:
        resp = (await _prompt_user("Proceed? [y/N]: ")).strip().lower()
        if resp != "y":
            print("[yellow]Aborted by user.[/yellow]")
            logging.info("Aborted by user.")
            for plan in plans:
                trades = plan["trades"]
                buy_usd = sum(t.notional for t in trades if t.action == "BUY")
                sell_usd = sum(t.notional for t in trades if t.action == "SELL")
                append_run_summary(
                    Path(cfg.io.report_dir),
                    ts_dt,
                    {
                        "timestamp_run": ts_dt.isoformat(),
                        "account_id": plan["account_id"],
                        "planned_orders": len(trades),
                        "submitted": 0,
                        "filled": 0,
                        "rejected": 0,
                        "buy_usd": buy_usd,
                        "sell_usd": sell_usd,
                        "pre_leverage": plan["pre_leverage"],
                        "post_leverage": plan["pre_leverage"],
                        "status": "aborted",
                        "error": "",
                    },
                )
            return failures
        args.yes = True

    use_parallel = parallel_accounts and args.yes and pacing_sec == 0
    output_lock: asyncio.Lock | None = None
    if use_parallel:
        output_lock = asyncio.Lock()

        async def start_after_delay(pl: Plan, delay: float) -> None:
            if delay:
                await asyncio.sleep(delay)
            await confirm_per_account(
                pl,
                args,
                cfg,
                ts_dt,
                client_factory=client_factory,
                submit_batch=submit_batch,
                append_run_summary=append_run_summary,
                write_post_trade_report=write_post_trade_report,
                compute_drift=compute_drift,
                prioritize_by_drift=prioritize_by_drift,
                size_orders=size_orders,
                output_lock=output_lock,
            )

        tasks = [
            asyncio.create_task(start_after_delay(pl, idx * pacing_sec))
            for idx, pl in enumerate(plans)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for pl, res in zip(plans, results):
            if isinstance(res, Exception):
                account_id = pl["account_id"]
                logging.exception(
                    "Unhandled error processing account %s", account_id, exc_info=res
                )
                async with output_lock:
                    print(f"[red]{res}[/red]")
                failures.append((account_id, str(res)))
        return failures

    sell_plans: list[Plan] = []
    buy_plans: list[Plan] = []
    for pl in plans:
        sell_trades = [t for t in pl["trades"] if t.action == "SELL"]
        buy_trades = [t for t in pl["trades"] if t.action == "BUY"]
        if sell_trades:
            sp = cast(Plan, dict(pl))
            sp["trades"] = sell_trades
            sp["planned_orders"] = len(sell_trades)
            sp["sell_usd"] = sum(t.notional for t in sell_trades)
            sp["buy_usd"] = 0.0
            sell_plans.append(sp)
        if buy_trades:
            bp = cast(Plan, dict(pl))
            bp["trades"] = buy_trades
            bp["planned_orders"] = len(buy_trades)
            bp["buy_usd"] = sum(t.notional for t in buy_trades)
            bp["sell_usd"] = 0.0
            buy_plans.append(bp)

    failed_accounts: set[str] = set()
    for idx, pl in enumerate(sell_plans):
        account_id = pl["account_id"]
        try:
            await confirm_per_account(
                pl,
                args,
                cfg,
                ts_dt,
                client_factory=client_factory,
                submit_batch=submit_batch,
                append_run_summary=append_run_summary,
                write_post_trade_report=write_post_trade_report,
                compute_drift=compute_drift,
                prioritize_by_drift=prioritize_by_drift,
                size_orders=size_orders,
                output_lock=None,
            )
        except (ConfigError, IBKRError, PlanningError) as exc:
            logging.error("Error processing account %s: %s", account_id, exc)
            print(f"[red]{exc}[/red]")
            failures.append((account_id, str(exc)))
            failed_accounts.add(account_id)
        except Exception as exc:  # noqa: BLE001
            logging.exception(
                "Unexpected error processing account %s", account_id, exc_info=exc
            )
            print(f"[red]{exc}[/red]")
            failures.append((account_id, str(exc)))
            failed_accounts.add(account_id)
        if idx < len(sell_plans) - 1:
            await asyncio.sleep(pacing_sec)

    if buy_plans:
        await asyncio.sleep(pacing_sec)
    for idx, pl in enumerate(buy_plans):
        account_id = pl["account_id"]
        if account_id in failed_accounts:
            continue
        try:
            await confirm_per_account(
                pl,
                args,
                cfg,
                ts_dt,
                client_factory=client_factory,
                submit_batch=submit_batch,
                append_run_summary=append_run_summary,
                write_post_trade_report=write_post_trade_report,
                compute_drift=compute_drift,
                prioritize_by_drift=prioritize_by_drift,
                size_orders=size_orders,
                output_lock=None,
            )
        except (ConfigError, IBKRError, PlanningError) as exc:
            logging.error("Error processing account %s: %s", account_id, exc)
            print(f"[red]{exc}[/red]")
            failures.append((account_id, str(exc)))
        except Exception as exc:  # noqa: BLE001
            logging.exception(
                "Unexpected error processing account %s", account_id, exc_info=exc
            )
            print(f"[red]{exc}[/red]")
            failures.append((account_id, str(exc)))
        await asyncio.sleep(pacing_sec)

    return failures
