import argparse
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import rebalance


def _setup(monkeypatch: pytest.MonkeyPatch):
    cfg = SimpleNamespace(
        ibkr=SimpleNamespace(host="h", port=1, client_id=1, read_only=False),
        models=SimpleNamespace(smurf=0.5, badass=0.3, gltr=0.2),
        pricing=SimpleNamespace(price_source="last", fallback_to_snapshot=True),
        execution=SimpleNamespace(
            order_type="MKT", algo_preference="adaptive", commission_report_timeout=5.0
        ),
        io=SimpleNamespace(report_dir="reports", log_level="INFO"),
        accounts=SimpleNamespace(ids=["good", "bad"]),
    )
    monkeypatch.setattr(rebalance, "load_config", lambda _p: cfg)

    async def fake_load_portfolios(paths, *, host, port, client_id):  # noqa: ARG001
        return {aid: {} for aid in paths}

    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)

    class FakeClient:
        def __init__(self):
            self._ib = object()

        async def connect(self, host, port, client_id):  # noqa: ARG002
            return None

        async def disconnect(self, host, port, client_id):  # noqa: ARG002
            return None

        async def snapshot(self, account_id):  # noqa: ARG002
            return {"positions": [], "cash": 0.0, "net_liq": 0.0}

    monkeypatch.setattr(rebalance, "IBKRClient", lambda: FakeClient())
    monkeypatch.setattr(rebalance, "_fetch_price", lambda ib, sym, cfg: (sym, 0.0))
    monkeypatch.setattr(rebalance, "size_orders", lambda *a, **k: ([], 0.0, 0.0))
    monkeypatch.setattr(rebalance, "render_preview", lambda *a, **k: "TABLE")
    monkeypatch.setattr(rebalance, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(
        rebalance, "write_pre_trade_report", lambda *a, **k: Path("pre")
    )

    def fake_compute_drift(account_id, *a, **k):
        if account_id == "bad":
            raise ValueError("boom")
        return []

    monkeypatch.setattr(rebalance, "compute_drift", fake_compute_drift)
    monkeypatch.setattr(
        rebalance, "prioritize_by_drift", lambda account_id, drifts, cfg: []
    )

    return argparse.Namespace(
        config="cfg", csv="csv", dry_run=True, yes=False, read_only=False
    )


def test_run_reports_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _setup(monkeypatch)
    failures = asyncio.run(rebalance._run(args))
    out = capsys.readouterr().out
    assert failures == [("bad", "boom")]
    assert "bad: boom" in out
    assert "TABLE" in out


def test_main_exits_nonzero_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(args):  # noqa: ARG001
        return [("a", "oops")]

    monkeypatch.setattr(rebalance, "_run", fake_run)
    with pytest.raises(SystemExit) as exc:
        rebalance.main()
    assert exc.value.code == 1


def test_parallel_task_exception_records_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = SimpleNamespace(
        ibkr=SimpleNamespace(host="h", port=1, client_id=1, read_only=False),
        models=SimpleNamespace(smurf=0.5, badass=0.3, gltr=0.2),
        pricing=SimpleNamespace(price_source="last", fallback_to_snapshot=True),
        execution=SimpleNamespace(
            order_type="MKT", algo_preference="adaptive", commission_report_timeout=5.0
        ),
        io=SimpleNamespace(report_dir="reports", log_level="INFO"),
        accounts=SimpleNamespace(ids=["good", "bad"], parallel=True),
    )
    monkeypatch.setattr(rebalance, "load_config", lambda _p: cfg)

    async def fake_load_portfolios(paths, *, host, port, client_id):  # noqa: ARG001
        return {aid: {} for aid in paths}

    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)

    async def fake_plan_account(account_id, portfolios, cfg_acct, ts_dt, **kwargs):
        if account_id == "bad":
            raise RuntimeError("kaboom")
        return {
            "account_id": account_id,
            "drifts": [],
            "trades": [],
            "prices": {},
            "current": {},
            "targets": {},
            "net_liq": 0.0,
            "pre_gross_exposure": 0.0,
            "pre_leverage": 0.0,
            "post_leverage": 0.0,
            "table": "TABLE",
            "planned_orders": 0,
            "buy_usd": 0.0,
            "sell_usd": 0.0,
        }

    monkeypatch.setattr(rebalance, "plan_account", fake_plan_account)
    monkeypatch.setattr(rebalance, "setup_logging", lambda *a, **k: None)

    statuses: dict[str, str] = {}

    def fake_append_run_summary(path, ts_dt, data):  # noqa: ARG001
        statuses[data["account_id"]] = data["status"]

    monkeypatch.setattr(rebalance, "append_run_summary", fake_append_run_summary)

    args = argparse.Namespace(
        config="cfg", csv="csv", dry_run=True, yes=False, read_only=False
    )

    failures = asyncio.run(rebalance._run(args))
    assert failures == [("bad", "kaboom")]
    assert statuses["good"] == "dry_run"
    assert statuses["bad"] == "failed"


def test_parallel_sleep_exception_records_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = SimpleNamespace(
        ibkr=SimpleNamespace(host="h", port=1, client_id=1, read_only=False),
        models=SimpleNamespace(smurf=0.5, badass=0.3, gltr=0.2),
        pricing=SimpleNamespace(price_source="last", fallback_to_snapshot=True),
        execution=SimpleNamespace(
            order_type="MKT", algo_preference="adaptive", commission_report_timeout=5.0
        ),
        io=SimpleNamespace(report_dir="reports", log_level="INFO"),
        accounts=SimpleNamespace(ids=["good", "bad"], parallel=True, pacing_sec=1.0),
    )
    monkeypatch.setattr(rebalance, "load_config", lambda _p: cfg)

    async def fake_load_portfolios(paths, *, host, port, client_id):  # noqa: ARG001
        return {aid: {} for aid in paths}

    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)

    async def fake_plan_account(account_id, portfolios, cfg_acct, ts_dt, **kwargs):
        return {
            "account_id": account_id,
            "planned_orders": 0,
            "buy_usd": 0.0,
            "sell_usd": 0.0,
            "pre_leverage": 0.0,
        }

    monkeypatch.setattr(rebalance, "plan_account", fake_plan_account)
    monkeypatch.setattr(rebalance, "setup_logging", lambda *a, **k: None)

    async def fake_confirm_per_account(
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
        append_run_summary(
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
                "status": "dry_run",
            },
        )

    monkeypatch.setattr(rebalance, "confirm_per_account", fake_confirm_per_account)

    sleep_calls = 0

    async def fake_sleep(delay):
        nonlocal sleep_calls
        sleep_calls += 1
        if delay and sleep_calls == 1:
            raise RuntimeError("boom")
        return None

    monkeypatch.setattr(rebalance.asyncio, "sleep", fake_sleep)

    rows: dict[str, dict[str, object]] = {}

    def fake_append_run_summary(path, ts_dt, data):  # noqa: ARG001
        rows[data["account_id"]] = data

    monkeypatch.setattr(rebalance, "append_run_summary", fake_append_run_summary)

    args = argparse.Namespace(
        config="cfg", csv="csv", dry_run=True, yes=False, read_only=False
    )

    failures = asyncio.run(rebalance._run(args))
    assert failures == [("bad", "boom")]
    assert rows["good"]["status"] == "dry_run"
    assert rows["bad"]["status"] == "failed"
    assert rows["bad"]["planned_orders"] == 0
