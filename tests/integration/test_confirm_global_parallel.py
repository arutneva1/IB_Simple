import asyncio
import csv
import sys
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.confirmation import confirm_global
from src.io.reporting import append_run_summary

pytestmark = pytest.mark.integration

confirm_starts: list[tuple[float, object]] = []
summary_rows: list[dict[str, object]] = []


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
    confirm_starts.append((time.perf_counter(), output_lock))
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
            parallel_accounts=True,
        )
    )

    assert len(confirm_starts) == 2
    assert all(lock is not None for _, lock in confirm_starts)
    assert abs(confirm_starts[1][0] - confirm_starts[0][0]) < 0.05
    assert len(summary_rows) == 2


def test_confirm_global_error_aggregation(monkeypatch, cfg):
    confirm_starts.clear()
    summary_rows.clear()

    async def faulty_confirm(plan, *args, **kwargs):
        if plan["account_id"] == "A2":
            confirm_starts.append((time.perf_counter(), kwargs.get("output_lock")))
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
            parallel_accounts=True,
        )
    )

    assert failures == [("A2", "boom")]
    statuses = {r["account_id"]: r["status"] for r in summary_rows}
    assert statuses == {"A1": "ok", "A2": "failed"}
    assert len(confirm_starts) == 2
    assert all(lock is not None for _, lock in confirm_starts)
    assert abs(confirm_starts[1][0] - confirm_starts[0][0]) < 0.05


def test_confirm_global_sequential(monkeypatch, cfg):
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
            parallel_accounts=False,
        )
    )

    assert len(confirm_starts) == 2
    assert all(lock is None for _, lock in confirm_starts)
    assert confirm_starts[1][0] - confirm_starts[0][0] >= 0.05
    assert len(summary_rows) == 2


def test_run_summary_file_well_formed(monkeypatch, cfg, tmp_path):
    """Confirm_global writes a valid run summary when running in parallel."""

    async def stub_confirm(
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
        row = {
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
        }
        if output_lock is not None:
            async with output_lock:
                append_run_summary(Path(cfg.io.report_dir), ts_dt, row)
        else:
            append_run_summary(Path(cfg.io.report_dir), ts_dt, row)

    monkeypatch.setattr("src.core.confirmation.confirm_per_account", stub_confirm)

    cfg.io.report_dir = str(tmp_path)

    args = SimpleNamespace(dry_run=False, yes=True, read_only=False)
    ts_dt = datetime.utcnow()
    plans = [_make_plan("A1"), _make_plan("A2")]

    asyncio.run(
        confirm_global(
            plans,
            args,
            cfg,
            ts_dt,
            client_factory=lambda: None,
            submit_batch=lambda *a, **k: [],
            append_run_summary=append_run_summary,
            write_post_trade_report=lambda *a, **k: Path(""),
            compute_drift=lambda *a, **k: [],
            prioritize_by_drift=lambda *a, **k: [],
            size_orders=lambda *a, **k: ([], 0, 0),
            parallel_accounts=True,
        )
    )

    report_files = list(Path(cfg.io.report_dir).glob("run_summary_*.csv"))
    assert len(report_files) == 1
    with report_files[0].open() as fh:
        rows = list(csv.DictReader(fh))
    assert {row["account_id"] for row in rows} == {"A1", "A2"}
