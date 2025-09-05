import asyncio
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.confirmation import confirm_global

pytestmark = pytest.mark.integration

confirm_starts = []
summary_rows = []


async def stub_confirm_per_account(
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
    output_lock=None,
):
    assert output_lock is not None
    confirm_starts.append(time.perf_counter())
    await asyncio.sleep(0.05)
    append_run_summary(
        Path(cfg.io.report_dir),
        ts_dt,
        {
            "timestamp_run": ts_dt.isoformat(),
            "account_id": plan["account_id"],
            "planned_orders": 0,
            "submitted": 0,
            "filled": 0,
            "rejected": 0,
            "buy_usd": 0.0,
            "sell_usd": 0.0,
            "pre_leverage": 0.0,
            "post_leverage": 0.0,
            "status": "ok",
            "error": "",
        },
    )


def _make_plan(account_id: str):
    return {
        "account_id": account_id,
        "table": "",
        "trades": [],
        "drifts": [],
        "prices": {},
        "current": {},
        "targets": {},
        "net_liq": 0.0,
        "pre_gross_exposure": 0.0,
        "pre_leverage": 0.0,
        "post_leverage": 0.0,
        "planned_orders": 0,
        "buy_usd": 0.0,
        "sell_usd": 0.0,
    }


@pytest.fixture
def cfg(tmp_path):
    return SimpleNamespace(
        ibkr=SimpleNamespace(read_only=False),
        io=SimpleNamespace(report_dir=str(tmp_path)),
        account_overrides={},
        rebalance=SimpleNamespace(min_order_usd=0),
    )


def test_confirm_global_concurrent(monkeypatch, cfg):
    confirm_starts.clear()
    summary_rows.clear()
    monkeypatch.setattr(
        "src.core.confirmation.confirm_per_account", stub_confirm_per_account
    )

    args = SimpleNamespace(dry_run=False, yes=True, read_only=False)
    ts_dt = datetime.utcnow()
    plans = [_make_plan("A1"), _make_plan("A2")]

    def append_summary(path, ts, row):
        summary_rows.append(row)

    asyncio.run(
        confirm_global(
            plans,
            args,
            cfg,
            ts_dt,
            client_factory=lambda: None,
            submit_batch=lambda *a, **k: [],
            append_run_summary=append_summary,
            write_post_trade_report=lambda *a, **k: Path(""),
            compute_drift=lambda *a, **k: [],
            prioritize_by_drift=lambda *a, **k: [],
            size_orders=lambda *a, **k: ([], 0, 0),
            pacing_sec=0.0,
        )
    )

    assert len(confirm_starts) == 2
    assert abs(confirm_starts[1] - confirm_starts[0]) < 0.05
    assert len(summary_rows) == 2


def test_confirm_global_error_aggregation(monkeypatch, cfg):
    confirm_starts.clear()
    summary_rows.clear()

    async def faulty_confirm(plan, *args, **kwargs):
        confirm_starts.append(time.perf_counter())
        if plan["account_id"] == "A2":
            raise RuntimeError("boom")
        return await stub_confirm_per_account(plan, *args, **kwargs)

    monkeypatch.setattr("src.core.confirmation.confirm_per_account", faulty_confirm)

    args = SimpleNamespace(dry_run=False, yes=True, read_only=False)
    ts_dt = datetime.utcnow()
    plans = [_make_plan("A1"), _make_plan("A2")]

    def append_summary(path, ts, row):
        summary_rows.append(row)

    failures = asyncio.run(
        confirm_global(
            plans,
            args,
            cfg,
            ts_dt,
            client_factory=lambda: None,
            submit_batch=lambda *a, **k: [],
            append_run_summary=append_summary,
            write_post_trade_report=lambda *a, **k: Path(""),
            compute_drift=lambda *a, **k: [],
            prioritize_by_drift=lambda *a, **k: [],
            size_orders=lambda *a, **k: ([], 0, 0),
            pacing_sec=0.0,
        )
    )

    assert failures == [("A2", "boom")]
    statuses = {r["account_id"]: r["status"] for r in summary_rows}
    assert statuses == {"A1": "ok", "A2": "failed"}
    assert abs(confirm_starts[1] - confirm_starts[0]) < 0.05
