import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.broker.errors import IBKRError
from src.core.sizing import SizedTrade

from src.core.confirmation import confirm_per_account
from src.io import (
    IBKR,
    IO,
    AccountOverride,
    Accounts,
    AppConfig,
    ConfirmMode,
    Execution,
    Models,
    Pricing,
    Rebalance,
)


def test_confirm_per_account_applies_overrides(tmp_path):
    cfg = AppConfig(
        ibkr=IBKR(host="localhost", port=4001, client_id=1, read_only=False),
        models=Models(smurf=0.5, badass=0.3, gltr=0.2),
        rebalance=Rebalance(
            trigger_mode="band",
            per_holding_band_bps=0,
            portfolio_total_band_bps=0,
            min_order_usd=10,
            cash_buffer_type="abs",
            cash_buffer_pct=None,
            cash_buffer_abs=0.0,
            allow_fractional=False,
            max_leverage=1.0,
            maintenance_buffer_pct=0.0,
            trading_hours="rth",
            max_passes=2,
        ),
        pricing=Pricing(price_source="last", fallback_to_snapshot=False),
        execution=Execution(
            order_type="market",
            algo_preference="adaptive",
            fallback_plain_market=False,
            batch_orders=False,
            commission_report_timeout=0.0,
            wait_before_fallback=0.0,
        ),
        io=IO(report_dir=str(tmp_path), log_level="INFO"),
        accounts=Accounts(ids=["ACC1"], confirm_mode=ConfirmMode.PER_ACCOUNT),
        account_overrides={"ACC1": AccountOverride(min_order_usd=100)},
    )

    plan = {
        "account_id": "ACC1",
        "trades": [],
        "drifts": [],
        "prices": {},
        "current": {"CASH": 1000.0},
        "targets": {},
        "net_liq": 1000.0,
        "pre_gross_exposure": 0.0,
        "pre_leverage": 0.0,
        "post_leverage": 0.0,
        "table": "",
        "planned_orders": 0,
        "buy_usd": 0.0,
        "sell_usd": 0.0,
    }

    args = SimpleNamespace(dry_run=False, read_only=False, yes=True)

    recorded = []

    def compute_drift(account_id, positions, targets, prices, net_liq, cfg):
        recorded.append(cfg.rebalance.min_order_usd)
        return []

    def prioritize_by_drift(account_id, drifts, cfg):
        return []

    def size_orders(account_id, drifts, prices, cash_after, net_liq, cfg):
        return [], 0.0, 0.0

    def append_run_summary(path, ts_dt, row):
        pass

    def write_post_trade_report(
        path,
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
    ):
        return path / "report.json"

    async def submit_batch(client, trades, cfg, account_id):
        return []

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    ts_dt = datetime.utcnow()
    asyncio.run(
        confirm_per_account(
            plan,
            args,
            cfg,
            ts_dt,
            client_factory=DummyClient,
            submit_batch=submit_batch,
            append_run_summary=append_run_summary,
            write_post_trade_report=write_post_trade_report,
            compute_drift=compute_drift,
            prioritize_by_drift=prioritize_by_drift,
            size_orders=size_orders,
        )
    )

    assert recorded == [100]


def test_confirm_per_account_reports_totals_for_same_symbol_buys_and_sells(tmp_path):
    cfg = AppConfig(
        ibkr=IBKR(host="localhost", port=4001, client_id=1, read_only=False),
        models=Models(smurf=0.5, badass=0.3, gltr=0.2),
        rebalance=Rebalance(
            trigger_mode="band",
            per_holding_band_bps=0,
            portfolio_total_band_bps=0,
            min_order_usd=10,
            cash_buffer_type="abs",
            cash_buffer_pct=None,
            cash_buffer_abs=0.0,
            allow_fractional=False,
            max_leverage=1.0,
            maintenance_buffer_pct=0.0,
            trading_hours="rth",
            max_passes=2,
        ),
        pricing=Pricing(price_source="last", fallback_to_snapshot=False),
        execution=Execution(
            order_type="market",
            algo_preference="adaptive",
            fallback_plain_market=False,
            commission_report_timeout=0.0,
            wait_before_fallback=0.0,
            batch_orders=False,
        ),
        io=IO(report_dir=str(tmp_path), log_level="INFO"),
        accounts=Accounts(ids=["ACC1"], confirm_mode=ConfirmMode.PER_ACCOUNT),
        account_overrides={},
    )

    plan = {
        "account_id": "ACC1",
        "trades": [SizedTrade("XYZ", "BUY", 1, 10.0)],
        "drifts": [],
        "prices": {"XYZ": 10.0},
        "current": {"CASH": 1000.0},
        "targets": {},
        "net_liq": 1000.0,
        "pre_gross_exposure": 0.0,
        "pre_leverage": 0.0,
        "post_leverage": 0.0,
        "table": "",
        "planned_orders": 1,
        "buy_usd": 10.0,
        "sell_usd": 0.0,
    }

    args = SimpleNamespace(dry_run=False, read_only=False, yes=True)

    appended = []

    async def submit_batch(client, trades, cfg, account_id):  # noqa: ARG001
        results = []
        for t in trades:
            price = 10.0 if t.action == "BUY" else 11.0
            results.append(
                {
                    "symbol": t.symbol,
                    "status": "Filled",
                    "fill_qty": t.quantity,
                    "fill_price": price,
                }
            )
        return results

    def compute_drift(account_id, positions, targets, prices, net_liq, cfg):  # noqa: ARG001
        return ["dummy"]

    def prioritize_by_drift(account_id, drifts, cfg):  # noqa: ARG001
        return drifts

    calls = {"n": 0}

    def size_orders(account_id, drifts, prices, cash_after, net_liq, cfg):  # noqa: ARG001
        if calls["n"] == 0:
            calls["n"] += 1
            return [SizedTrade("XYZ", "SELL", 1, 11.0)], 0.0, 0.0
        return [], 0.0, 0.0

    def append_run_summary(path, ts_dt, row):  # noqa: ARG001
        appended.append(row)

    def write_post_trade_report(
        path,
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
    ):  # noqa: ARG001
        return path / "report.json"

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    ts_dt = datetime.utcnow()
    asyncio.run(
        confirm_per_account(
            plan,
            args,
            cfg,
            ts_dt,
            client_factory=DummyClient,
            submit_batch=submit_batch,
            append_run_summary=append_run_summary,
            write_post_trade_report=write_post_trade_report,
            compute_drift=compute_drift,
            prioritize_by_drift=prioritize_by_drift,
            size_orders=size_orders,
        )
    )

    summary = appended[0]
    assert summary["buy_usd"] == 10.0
    assert summary["sell_usd"] == 11.0


def test_confirm_per_account_logs_failed_summary(tmp_path):
    cfg = AppConfig(
        ibkr=IBKR(host="localhost", port=4001, client_id=1, read_only=False),
        models=Models(smurf=0.5, badass=0.3, gltr=0.2),
        rebalance=Rebalance(
            trigger_mode="band",
            per_holding_band_bps=0,
            portfolio_total_band_bps=0,
            min_order_usd=10,
            cash_buffer_type="abs",
            cash_buffer_pct=None,
            cash_buffer_abs=0.0,
            allow_fractional=False,
            max_leverage=1.0,
            maintenance_buffer_pct=0.0,
            trading_hours="rth",
            max_passes=2,
        ),
        pricing=Pricing(price_source="last", fallback_to_snapshot=False),
        execution=Execution(
            order_type="market",
            algo_preference="adaptive",
            fallback_plain_market=False,
            commission_report_timeout=0.0,
            wait_before_fallback=0.0,
            batch_orders=False,
        ),
        io=IO(report_dir=str(tmp_path), log_level="INFO"),
        accounts=Accounts(ids=["ACC1"], confirm_mode=ConfirmMode.PER_ACCOUNT),
        account_overrides={},
    )

    plan = {
        "account_id": "ACC1",
        "trades": [SizedTrade("XYZ", "BUY", 1, 10.0)],
        "drifts": [],
        "prices": {"XYZ": 10.0},
        "current": {"CASH": 1000.0},
        "targets": {},
        "net_liq": 1000.0,
        "pre_gross_exposure": 0.0,
        "pre_leverage": 0.0,
        "post_leverage": 0.0,
        "table": "",
        "planned_orders": 1,
        "buy_usd": 10.0,
        "sell_usd": 0.0,
    }

    args = SimpleNamespace(dry_run=False, read_only=False, yes=True)

    appended: list[dict[str, Any]] = []

    async def submit_batch(client, trades, cfg, account_id):  # noqa: ARG001
        return [
            {
                "symbol": trades[0].symbol,
                "status": "Rejected",
                "fill_qty": 0,
                "fill_price": 0.0,
            }
        ]

    def append_run_summary(path, ts_dt, row):  # noqa: ARG001
        appended.append(row)

    def write_post_trade_report(
        path,
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
    ):
        return path / "report.json"

    def compute_drift(account_id, positions, targets, prices, net_liq, cfg):  # noqa: ARG001
        return []

    def prioritize_by_drift(account_id, drifts, cfg):  # noqa: ARG001
        return []

    def size_orders(account_id, drifts, prices, cash_after, net_liq, cfg):  # noqa: ARG001
        return [], 0.0, 0.0

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: D401
            pass

    ts_dt = datetime.utcnow()

    with pytest.raises(IBKRError):
        asyncio.run(
            confirm_per_account(
                plan,
                args,
                cfg,
                ts_dt,
                client_factory=DummyClient,
                submit_batch=submit_batch,
                append_run_summary=append_run_summary,
                write_post_trade_report=write_post_trade_report,
                compute_drift=compute_drift,
                prioritize_by_drift=prioritize_by_drift,
                size_orders=size_orders,
            )
        )

    assert len(appended) == 1
    row = appended[0]
    assert row["status"] == "failed"
    assert row["planned_orders"] == 1
    assert row["submitted"] == 1
    assert row["filled"] == 0
    assert row["rejected"] == 1
    assert row["buy_usd"] == 0.0
    assert row["sell_usd"] == 0.0
    assert row["error"] == "One or more orders failed to fill"
