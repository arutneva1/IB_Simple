import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.confirmation import confirm_per_account
from src.core.sizing import SizedTrade
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


def test_summary_reports_planned_and_executed_counts(tmp_path):
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
        account_overrides={"ACC1": AccountOverride(min_order_usd=10)},
    )

    plan = {
        "account_id": "ACC1",
        "trades": [SizedTrade("XYZ", "BUY", 1, 10.0)],
        "drifts": [],
        "prices": {"XYZ": 10.0, "ABC": 10.0},
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

    appended: list[dict] = []

    async def submit_batch(client, trades, cfg, account_id):  # noqa: ARG001
        results = []
        for t in trades:
            results.append(
                {
                    "symbol": t.symbol,
                    "status": "Filled",
                    "fill_qty": t.quantity,
                    "fill_price": 10.0,
                }
            )
        return results

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

    def compute_drift(
        account_id, positions, targets, prices, net_liq, cfg
    ):  # noqa: ARG001
        return []

    def prioritize_by_drift(account_id, drifts, cfg):  # noqa: ARG001
        return drifts

    call_count = {"n": 0}

    def size_orders(
        account_id, drifts, prices, cash_after, net_liq, cfg
    ):  # noqa: ARG001
        if call_count["n"] == 0:
            call_count["n"] += 1
            return [SizedTrade("ABC", "BUY", 1, 10.0)], 10.0, 0.0
        return [], 0.0, 0.0

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

    assert len(appended) == 1
    row = appended[0]
    assert row["planned_orders"] == 1
    assert row["submitted"] == 2
