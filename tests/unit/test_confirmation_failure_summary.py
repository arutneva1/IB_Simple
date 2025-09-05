import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.broker.errors import IBKRError  # noqa: E402
from src.core import confirmation  # noqa: E402
from src.core.confirmation import confirm_global  # noqa: E402
from src.core.sizing import SizedTrade  # noqa: E402
from src.io import (  # noqa: E402
    IBKR,
    IO,
    Accounts,
    AppConfig,
    ConfirmMode,
    Execution,
    Models,
    Pricing,
    Rebalance,
)
from src.io.reporting import append_run_summary  # noqa: E402


def test_failing_confirmation_writes_single_summary(tmp_path, monkeypatch):
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
            max_passes=1,
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
        accounts=Accounts(ids=["ACC1"], confirm_mode=ConfirmMode.GLOBAL),
    )

    plan = {
        "account_id": "ACC1",
        "trades": [SizedTrade("XYZ", "BUY", 1, 10.0)],
        "drifts": [],
        "prices": {"XYZ": 10.0},
        "current": {"CASH": 100.0},
        "targets": {},
        "net_liq": 100.0,
        "pre_gross_exposure": 0.0,
        "pre_leverage": 0.0,
        "post_leverage": 0.0,
        "table": "",
        "planned_orders": 1,
        "buy_usd": 10.0,
        "sell_usd": 0.0,
    }

    args = SimpleNamespace(dry_run=False, read_only=False, yes=True)
    ts_dt = datetime.utcnow()
    summary_path: dict[str, Path] = {}

    async def failing_confirm_per_account(
        plan,
        args,
        cfg,
        ts_dt,
        *,
        client_factory,
        submit_batch,
        append_run_summary,
        write_post_trade_report,
        compute_drift,
        prioritize_by_drift,
        size_orders,
        output_lock,
    ):
        summary_path["path"] = append_run_summary(
            Path(cfg.io.report_dir),
            ts_dt,
            {
                "timestamp_run": ts_dt.isoformat(),
                "account_id": plan["account_id"],
                "planned_orders": plan["planned_orders"],
                "submitted": 0,
                "filled": 0,
                "rejected": 0,
                "buy_usd": plan["buy_usd"],
                "sell_usd": plan["sell_usd"],
                "pre_leverage": plan["pre_leverage"],
                "post_leverage": plan["pre_leverage"],
                "status": "failed",
                "error": "boom",
            },
        )
        raise IBKRError("boom")

    monkeypatch.setattr(
        confirmation, "confirm_per_account", failing_confirm_per_account
    )

    failures = asyncio.run(
        confirm_global(
            [plan],
            args,
            cfg,
            ts_dt,
            client_factory=lambda: object(),
            submit_batch=lambda *a, **k: [],
            append_run_summary=append_run_summary,
            write_post_trade_report=lambda *a, **k: tmp_path / "report.json",
            compute_drift=lambda *a, **k: [],
            prioritize_by_drift=lambda *a, **k: [],
            size_orders=lambda *a, **k: ([], 0.0, 0.0),
            pacing_sec=0.0,
            parallel_accounts=False,
        )
    )

    assert failures == [("ACC1", "boom")]
    path = summary_path["path"]
    with path.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["account_id"] == "ACC1"
    assert rows[0]["status"] == "failed"
