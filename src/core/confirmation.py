from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, cast

from src.broker.errors import IBKRError
from src.broker.ibkr_client import IBKRClient
from src.core.errors import PlanningError
from src.core.planner import Plan
from src.io import AppConfig, ConfigError, merge_account_overrides


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
) -> None:
    """Handle confirmation, execution, and reporting for a single account."""

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
    buy_usd = plan["buy_usd"]
    sell_usd = plan["sell_usd"]

    print(table)
    if args.dry_run:
        print("[green]Dry run complete (no orders submitted).[/green]")
        logging.info("Dry run complete (no orders submitted).")
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
                "post_leverage": post_leverage,
                "status": "dry_run",
                "error": "",
            },
        )
        return

    if cfg.ibkr.read_only or args.read_only:
        print(
            "[yellow]Read-only mode: trading is disabled; no orders will be submitted.[/yellow]"
        )
        logging.info(
            "Read-only mode: trading is disabled; no orders will be submitted."
        )
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
                "status": "read_only",
                "error": "",
            },
        )
        return

    if not args.yes:
        resp = input("Proceed? [y/N]: ").strip().lower()
        if resp != "y":
            print("[yellow]Aborted by user.[/yellow]")
            logging.info("Aborted by user.")
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
                    "status": "aborted",
                    "error": "",
                },
            )
            return

    print("[blue]Submitting batch market orders[/blue]")
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
        print(
            f"[green]{res.get('symbol')}: {res.get('status')} {qty} @ {price}[/green]"
        )
        logging.info("%s: %s %s @ %s", res.get("symbol"), res.get("status"), qty, price)
    if any(r.get("status") != "Filled" for r in results):
        logging.error("One or more orders failed to fill")
        raise IBKRError("One or more orders failed to fill")

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
        if price <= 0:
            price = prices.get(trade.symbol, 0.0)
        if trade.action == "BUY":
            positions[trade.symbol] = positions.get(trade.symbol, 0.0) + filled
            cash_after -= filled * price
        else:
            positions[trade.symbol] = positions.get(trade.symbol, 0.0) - filled
            cash_after += filled * price
        prices[trade.symbol] = price
    positions["CASH"] = cash_after

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
            account_id, iter_prioritized, prices, cash_after, net_liq, cfg
        )
        if not extra_trades:
            break
        print(
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
            print(
                f"[green]{res.get('symbol')}: {res.get('status')} {qty} @ {price}[/green]"
            )
            logging.info(
                "%s: %s %s @ %s", res.get("symbol"), res.get("status"), qty, price
            )
        if any(r.get("status") != "Filled" for r in extra_results):
            logging.error("One or more orders failed to fill")
            raise IBKRError("One or more orders failed to fill")
        results_by_symbol = {r.get("symbol"): r for r in extra_results}
        for trade in extra_trades:
            res = results_by_symbol.get(trade.symbol, {})
            filled_any = res.get("fill_qty")
            if filled_any is None:
                filled_any = res.get("filled", trade.quantity)
            filled = float(filled_any)
            price_any = res.get("fill_price")
            if price_any is None:
                price_any = res.get("avg_fill_price", prices.get(trade.symbol, 0.0))
            price = float(price_any)
            if price <= 0:
                price = prices.get(trade.symbol, 0.0)
            if trade.action == "BUY":
                positions[trade.symbol] = positions.get(trade.symbol, 0.0) + filled
                cash_after -= filled * price
            else:
                positions[trade.symbol] = positions.get(trade.symbol, 0.0) - filled
                cash_after += filled * price
            prices[trade.symbol] = price
        positions["CASH"] = cash_after
        all_trades.extend(extra_trades)
        all_results.extend(extra_results)
        passes += 1

    post_gross_exposure_actual = net_liq - cash_after
    post_leverage_actual = post_gross_exposure_actual / net_liq if net_liq else 0.0
    trades_by_symbol = {t.symbol: t for t in all_trades}
    filled = sum(1 for r in all_results if r.get("status") == "Filled")
    rejected = len(all_results) - filled
    buy_usd = 0.0
    sell_usd = 0.0
    for r in all_results:
        sym_any = r.get("symbol")
        if not isinstance(sym_any, str):
            continue
        matched_trade = trades_by_symbol.get(sym_any)
        if matched_trade is None:
            continue
        qty_any = r.get("fill_qty")
        if qty_any is None:
            qty_any = r.get("filled", 0.0)
        price_any = r.get("fill_price")
        if price_any is None:
            price_any = r.get("avg_fill_price", 0.0)
        value = float(qty_any) * float(price_any)
        if matched_trade.action == "BUY":
            buy_usd += value
        else:
            sell_usd += value
    trades = all_trades
    results = all_results
    planned_orders = len(trades)
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
    append_run_summary(
        Path(cfg.io.report_dir),
        ts_dt,
        {
            "timestamp_run": ts_dt.isoformat(),
            "account_id": account_id,
            "planned_orders": planned_orders,
            "submitted": len(trades),
            "filled": filled,
            "rejected": rejected,
            "buy_usd": buy_usd,
            "sell_usd": sell_usd,
            "pre_leverage": pre_leverage,
            "post_leverage": post_leverage_actual,
            "status": "completed",
            "error": "",
        },
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
) -> list[tuple[str, str]]:
    """Handle global confirmation workflow for multiple accounts."""

    for plan in plans:
        print(plan["table"])

    failures: list[tuple[str, str]] = []
    cfg_by_account: dict[str, AppConfig] = {}

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
        resp = input("Proceed? [y/N]: ").strip().lower()
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

    # Phase 1: submit sells
    for plan in plans:
        account_id = plan["account_id"]
        cfg_acc = cfg_by_account.get(account_id)
        if cfg_acc is None:
            cfg_acc = merge_account_overrides(cfg, account_id)
            cfg_by_account[account_id] = cfg_acc
        trades = plan["trades"]
        sell_trades = [t for t in trades if t.action == "SELL"]
        try:
            print("[blue]Submitting sell orders[/blue]")
            logging.info("Submitting sell orders for %s", account_id)
            client = client_factory()
            if hasattr(client, "__aenter__"):
                setattr(client, "_host", cfg_acc.ibkr.host)
                setattr(client, "_port", cfg_acc.ibkr.port)
                setattr(client, "_client_id", cfg_acc.ibkr.client_id)
                async with client:
                    plan["sell_results"] = await submit_batch(
                        client, sell_trades, cfg_acc, account_id
                    )
            else:
                await client.connect(
                    cfg_acc.ibkr.host, cfg_acc.ibkr.port, cfg_acc.ibkr.client_id
                )
                try:
                    plan["sell_results"] = await submit_batch(
                        client, sell_trades, cfg_acc, account_id
                    )
                finally:
                    await client.disconnect(
                        cfg_acc.ibkr.host, cfg_acc.ibkr.port, cfg_acc.ibkr.client_id
                    )
            sell_results = cast(list[dict[str, Any]], plan.get("sell_results", []))
            for res in sell_results:
                qty = res.get("fill_qty", res.get("filled", 0))
                price = res.get("fill_price", res.get("avg_fill_price", 0))
                print(
                    f"[green]{res.get('symbol')}: {res.get('status')} {qty} @ {price}[/green]"
                )
                logging.info(
                    "%s: %s %s @ %s",
                    res.get("symbol"),
                    res.get("status"),
                    qty,
                    price,
                )
        except (ConfigError, IBKRError, PlanningError) as exc:
            logging.error("Error processing account %s: %s", account_id, exc)
            print(f"[red]{exc}[/red]")
            failures.append((account_id, str(exc)))
            plan["failed"] = True
            buy_usd = sum(t.notional for t in trades if t.action == "BUY")
            sell_usd = sum(t.notional for t in trades if t.action == "SELL")
            append_run_summary(
                Path(cfg.io.report_dir),
                ts_dt,
                {
                    "timestamp_run": ts_dt.isoformat(),
                    "account_id": account_id,
                    "planned_orders": len(trades),
                    "submitted": 0,
                    "filled": 0,
                    "rejected": 0,
                    "buy_usd": buy_usd,
                    "sell_usd": sell_usd,
                    "pre_leverage": plan["pre_leverage"],
                    "post_leverage": plan["pre_leverage"],
                    "status": "failed",
                    "error": str(exc),
                },
            )
        finally:
            await asyncio.sleep(pacing_sec)

    # Phase 2: submit buys
    for plan in plans:
        if cast(bool, plan.get("failed")):
            continue
        account_id = plan["account_id"]
        cfg_acc = cfg_by_account.get(account_id)
        if cfg_acc is None:
            cfg_acc = merge_account_overrides(cfg, account_id)
            cfg_by_account[account_id] = cfg_acc
        trades = plan["trades"]
        buy_trades = [t for t in trades if t.action == "BUY"]
        try:
            print("[blue]Submitting buy orders[/blue]")
            logging.info("Submitting buy orders for %s", account_id)
            client = client_factory()
            if hasattr(client, "__aenter__"):
                setattr(client, "_host", cfg_acc.ibkr.host)
                setattr(client, "_port", cfg_acc.ibkr.port)
                setattr(client, "_client_id", cfg_acc.ibkr.client_id)
                async with client:
                    plan["buy_results"] = await submit_batch(
                        client, buy_trades, cfg_acc, account_id
                    )
            else:
                await client.connect(
                    cfg_acc.ibkr.host, cfg_acc.ibkr.port, cfg_acc.ibkr.client_id
                )
                try:
                    plan["buy_results"] = await submit_batch(
                        client, buy_trades, cfg_acc, account_id
                    )
                finally:
                    await client.disconnect(
                        cfg_acc.ibkr.host, cfg_acc.ibkr.port, cfg_acc.ibkr.client_id
                    )
            buy_results = cast(list[dict[str, Any]], plan.get("buy_results", []))
            for res in buy_results:
                qty = res.get("fill_qty", res.get("filled", 0))
                price = res.get("fill_price", res.get("avg_fill_price", 0))
                print(
                    f"[green]{res.get('symbol')}: {res.get('status')} {qty} @ {price}[/green]"
                )
                logging.info(
                    "%s: %s %s @ %s",
                    res.get("symbol"),
                    res.get("status"),
                    qty,
                    price,
                )
        except (ConfigError, IBKRError, PlanningError) as exc:
            logging.error("Error processing account %s: %s", account_id, exc)
            print(f"[red]{exc}[/red]")
            failures.append((account_id, str(exc)))
            plan["failed"] = True
            buy_usd = sum(t.notional for t in trades if t.action == "BUY")
            sell_usd = sum(t.notional for t in trades if t.action == "SELL")
            sell_results = cast(list[dict[str, Any]], plan.get("sell_results", []))
            append_run_summary(
                Path(cfg.io.report_dir),
                ts_dt,
                {
                    "timestamp_run": ts_dt.isoformat(),
                    "account_id": account_id,
                    "planned_orders": len(trades),
                    "submitted": len(sell_results),
                    "filled": 0,
                    "rejected": 0,
                    "buy_usd": buy_usd,
                    "sell_usd": sell_usd,
                    "pre_leverage": plan["pre_leverage"],
                    "post_leverage": plan["pre_leverage"],
                    "status": "failed",
                    "error": str(exc),
                },
            )
        finally:
            await asyncio.sleep(pacing_sec)

    # Phase 3: finalize
    for plan in plans:
        if cast(bool, plan.get("failed")):
            continue
        account_id = plan["account_id"]
        cfg_acc = cfg_by_account.get(account_id)
        if cfg_acc is None:
            cfg_acc = merge_account_overrides(cfg, account_id)
            cfg_by_account[account_id] = cfg_acc
        trades = plan["trades"]
        prices = plan["prices"]
        current = plan["current"]
        net_liq = plan["net_liq"]
        drifts = plan["drifts"]
        pre_gross_exposure = plan["pre_gross_exposure"]
        pre_leverage = plan["pre_leverage"]
        sell_results = cast(list[dict[str, Any]], plan.get("sell_results", []))
        buy_results = cast(list[dict[str, Any]], plan.get("buy_results", []))
        results = sell_results + buy_results
        planned_orders = len(trades)

        if any(r.get("status") != "Filled" for r in results):
            logging.error("One or more orders failed to fill")
            failures.append((account_id, "unfilled orders"))
            buy_usd = sum(t.notional for t in trades if t.action == "BUY")
            sell_usd = sum(t.notional for t in trades if t.action == "SELL")
            append_run_summary(
                Path(cfg.io.report_dir),
                ts_dt,
                {
                    "timestamp_run": ts_dt.isoformat(),
                    "account_id": account_id,
                    "planned_orders": planned_orders,
                    "submitted": len(results),
                    "filled": 0,
                    "rejected": len(results),
                    "buy_usd": buy_usd,
                    "sell_usd": sell_usd,
                    "pre_leverage": pre_leverage,
                    "post_leverage": pre_leverage,
                    "status": "failed",
                    "error": "unfilled orders",
                },
            )
            continue

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
            if price <= 0:
                price = prices.get(trade.symbol, 0.0)
            if trade.action == "BUY":
                positions[trade.symbol] = positions.get(trade.symbol, 0.0) + filled
                cash_after -= filled * price
            else:
                positions[trade.symbol] = positions.get(trade.symbol, 0.0) - filled
                cash_after += filled * price
            prices[trade.symbol] = price
        positions["CASH"] = cash_after

        all_trades = list(trades)
        all_results = list(results)
        max_passes = getattr(cfg_acc.rebalance, "max_passes", 1)
        passes = 1
        targets = plan["targets"]
        while passes < max_passes:
            buffer_type = getattr(cfg_acc.rebalance, "cash_buffer_type", "pct")
            if buffer_type == "pct":
                reserve = net_liq * getattr(
                    cfg_acc.rebalance, "cash_buffer_pct", 0.0
                )
            else:
                reserve = getattr(cfg_acc.rebalance, "cash_buffer_abs", 0.0)
            available_cash = cash_after - reserve
            if available_cash < cfg_acc.rebalance.min_order_usd:
                break
            iter_drifts = compute_drift(
                account_id, positions, targets, prices, net_liq, cfg_acc
            )
            iter_prioritized = prioritize_by_drift(account_id, iter_drifts, cfg_acc)
            extra_trades, _, _ = size_orders(
                account_id, iter_prioritized, prices, cash_after, net_liq, cfg_acc
            )
            if not extra_trades:
                break
            print(
                f"[blue]Submitting additional batch market orders (pass {passes + 1})[/blue]"
            )
            logging.info(
                "Submitting batch market orders for %s (pass %d)",
                account_id,
                passes + 1,
            )
            client = client_factory()
            if hasattr(client, "__aenter__"):
                setattr(client, "_host", cfg_acc.ibkr.host)
                setattr(client, "_port", cfg_acc.ibkr.port)
                setattr(client, "_client_id", cfg_acc.ibkr.client_id)
                async with client:
                    extra_results = await submit_batch(
                        client, extra_trades, cfg_acc, account_id
                    )
            else:
                await client.connect(
                    cfg_acc.ibkr.host, cfg_acc.ibkr.port, cfg_acc.ibkr.client_id
                )
                try:
                    extra_results = await submit_batch(
                        client, extra_trades, cfg_acc, account_id
                    )
                finally:
                    await client.disconnect(
                        cfg_acc.ibkr.host, cfg_acc.ibkr.port, cfg_acc.ibkr.client_id
                    )
            for res in extra_results:
                qty = res.get("fill_qty", res.get("filled", 0))
                price = res.get("fill_price", res.get("avg_fill_price", 0))
                print(
                    f"[green]{res.get('symbol')}: {res.get('status')} {qty} @ {price}[/green]"
                )
                logging.info(
                    "%s: %s %s @ %s",
                    res.get("symbol"),
                    res.get("status"),
                    qty,
                    price,
                )
            if any(r.get("status") != "Filled" for r in extra_results):
                logging.error("One or more orders failed to fill")
                raise IBKRError("One or more orders failed to fill")
            results_by_symbol = {r.get("symbol"): r for r in extra_results}
            for trade in extra_trades:
                res = results_by_symbol.get(trade.symbol, {})
                filled_any = res.get("fill_qty")
                if filled_any is None:
                    filled_any = res.get("filled", trade.quantity)
                filled = float(filled_any)
                price_any = res.get("fill_price")
                if price_any is None:
                    price_any = res.get("avg_fill_price", prices.get(trade.symbol, 0.0))
                price = float(price_any)
                if price <= 0:
                    price = prices.get(trade.symbol, 0.0)
                if trade.action == "BUY":
                    positions[trade.symbol] = positions.get(trade.symbol, 0.0) + filled
                    cash_after -= filled * price
                else:
                    positions[trade.symbol] = positions.get(trade.symbol, 0.0) - filled
                    cash_after += filled * price
                prices[trade.symbol] = price
            positions["CASH"] = cash_after
            all_trades.extend(extra_trades)
            all_results.extend(extra_results)
            passes += 1

        post_gross_exposure_actual = net_liq - cash_after
        post_leverage_actual = post_gross_exposure_actual / net_liq if net_liq else 0.0
        trades_by_symbol = {t.symbol: t for t in all_trades}
        filled = sum(1 for r in all_results if r.get("status") == "Filled")
        rejected = len(all_results) - filled
        buy_usd = 0.0
        sell_usd = 0.0
        for r in all_results:
            sym_any = r.get("symbol")
            if not isinstance(sym_any, str):
                continue
            matched_trade = trades_by_symbol.get(sym_any)
            if matched_trade is None:
                continue
            qty_any = r.get("fill_qty")
            if qty_any is None:
                qty_any = r.get("filled", 0.0)
            price_any = r.get("fill_price")
            if price_any is None:
                price_any = r.get("avg_fill_price", 0.0)
            value = float(qty_any) * float(price_any)
            if matched_trade.action == "BUY":
                buy_usd += value
            else:
                sell_usd += value
        trades = all_trades
        results = all_results
        planned_orders = len(trades)
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
        append_run_summary(
            Path(cfg.io.report_dir),
            ts_dt,
            {
                "timestamp_run": ts_dt.isoformat(),
                "account_id": account_id,
                "planned_orders": planned_orders,
                "submitted": len(trades),
                "filled": filled,
                "rejected": rejected,
                "buy_usd": buy_usd,
                "sell_usd": sell_usd,
                "pre_leverage": pre_leverage,
                "post_leverage": post_leverage_actual,
                "status": "completed",
                "error": "",
            },
        )

    return failures
