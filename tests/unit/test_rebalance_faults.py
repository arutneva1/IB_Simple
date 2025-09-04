from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from src import rebalance
from src.broker.errors import IBKRError


def test_partial_account_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """One account succeeds while another raises IBKRError."""

    cfg = SimpleNamespace(
        ibkr=SimpleNamespace(host="h", port=1, client_id=1, read_only=False),
        models=SimpleNamespace(smurf=0.5, badass=0.3, gltr=0.2),
        pricing=SimpleNamespace(price_source="last", fallback_to_snapshot=True),
        execution=SimpleNamespace(
            order_type="MKT", algo_preference="adaptive", commission_report_timeout=5.0
        ),
        io=SimpleNamespace(report_dir="reports", log_level="INFO"),
        accounts=SimpleNamespace(ids=["good", "bad"], pacing_sec=1),
    )
    monkeypatch.setattr(rebalance, "load_config", lambda _p: cfg)

    async def fake_load_portfolios(path, *, host, port, client_id):  # noqa: ARG001
        return {}

    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)

    class FakeClient:
        def __init__(self) -> None:
            self._ib = object()

        async def connect(self, host, port, client_id):  # noqa: ARG002
            return None

        async def disconnect(self, host, port, client_id):  # noqa: ARG002
            return None

        async def snapshot(self, account_id):  # noqa: ARG001
            if account_id == "bad":
                raise IBKRError("boom")
            return {"positions": [], "cash": 0.0, "net_liq": 0.0}

    monkeypatch.setattr(rebalance, "IBKRClient", lambda: FakeClient())
    monkeypatch.setattr(rebalance, "compute_drift", lambda *a, **k: [])
    monkeypatch.setattr(
        rebalance, "prioritize_by_drift", lambda account_id, drifts, cfg: []
    )
    monkeypatch.setattr(rebalance, "size_orders", lambda *a, **k: ([], 0.0, 0.0))
    monkeypatch.setattr(rebalance, "render_preview", lambda *a, **k: "TABLE")
    monkeypatch.setattr(rebalance, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(
        rebalance, "write_pre_trade_report", lambda *a, **k: Path("pre")
    )

    statuses: dict[str, str] = {}

    def fake_append_run_summary(path, ts_dt, data):  # noqa: ARG001
        statuses[data["account_id"]] = data["status"]

    monkeypatch.setattr(rebalance, "append_run_summary", fake_append_run_summary)

    sleep_calls: list[float] = []

    async def fake_sleep(duration):
        sleep_calls.append(duration)

    monkeypatch.setattr(rebalance.asyncio, "sleep", fake_sleep)

    with pytest.raises(SystemExit) as exc:
        rebalance.main(["--dry-run"])

    assert exc.value.code == 1
    assert statuses["good"] == "dry_run"
    assert statuses["bad"] == "failed"
    assert len(sleep_calls) == 2


def test_global_confirmation_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Global confirm mode respects pacing even when an account fails."""

    cfg = SimpleNamespace(
        ibkr=SimpleNamespace(host="h", port=1, client_id=1, read_only=False),
        models=SimpleNamespace(smurf=0.5, badass=0.3, gltr=0.2),
        pricing=SimpleNamespace(price_source="last", fallback_to_snapshot=True),
        execution=SimpleNamespace(
            order_type="MKT", algo_preference="adaptive", commission_report_timeout=5.0
        ),
        io=SimpleNamespace(report_dir="reports", log_level="INFO"),
        accounts=SimpleNamespace(ids=["bad", "good"], pacing_sec=1),
        rebalance=SimpleNamespace(min_order_usd=0, max_passes=1),
    )
    monkeypatch.setattr(rebalance, "load_config", lambda _p: cfg)

    async def fake_load_portfolios(path, *, host, port, client_id):  # noqa: ARG001
        return {}

    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)

    async def fake_plan_account(account_id, portfolios, cfg, ts_dt, **kwargs):
        trade_sell = SimpleNamespace(action="SELL", symbol="AAA", quantity=1, notional=1.0)
        trade_buy = SimpleNamespace(action="BUY", symbol="BBB", quantity=1, notional=1.0)
        return {
            "account_id": account_id,
            "drifts": [],
            "trades": [trade_sell, trade_buy],
            "prices": {"AAA": 1.0, "BBB": 1.0},
            "current": {"AAA": 1.0, "BBB": 0.0, "CASH": 0.0},
            "targets": {},
            "net_liq": 0.0,
            "pre_gross_exposure": 0.0,
            "pre_leverage": 0.0,
            "post_leverage": 0.0,
            "table": "TABLE",
            "planned_orders": 2,
            "buy_usd": 1.0,
            "sell_usd": 1.0,
        }

    monkeypatch.setattr(rebalance, "plan_account", fake_plan_account)

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
            return False

    monkeypatch.setattr(rebalance, "IBKRClient", lambda: FakeClient())

    events: list[tuple[str, str]] = []

    async def fake_submit_batch(client, trades, cfg, account_id):  # noqa: ARG001
        phase = "buy" if all(t.action == "BUY" for t in trades) else "sell"
        events.append((account_id, phase))
        if account_id == "bad" and phase == "sell":
            raise IBKRError("boom")
        return [
            {
                "symbol": t.symbol,
                "status": "Filled",
                "fill_qty": t.quantity,
                "fill_price": 1.0,
            }
            for t in trades
        ]

    monkeypatch.setattr(rebalance, "submit_batch", fake_submit_batch)
    monkeypatch.setattr(rebalance, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(rebalance, "render_preview", lambda *a, **k: "TABLE")
    monkeypatch.setattr(rebalance, "write_pre_trade_report", lambda *a, **k: Path("pre"))
    monkeypatch.setattr(rebalance, "append_run_summary", lambda *a, **k: None)
    monkeypatch.setattr(rebalance, "write_post_trade_report", lambda *a, **k: Path("post"))

    sleep_calls: list[float] = []

    async def fake_sleep(duration):
        sleep_calls.append(duration)

    monkeypatch.setattr(rebalance.asyncio, "sleep", fake_sleep)
    from src.core import confirmation

    monkeypatch.setattr(confirmation.asyncio, "sleep", fake_sleep)

    args = SimpleNamespace(
        config="cfg",
        csv="csv",
        dry_run=False,
        yes=True,
        read_only=False,
        confirm_mode="global",
    )

    failures = asyncio.run(rebalance._run(args))

    assert failures == [("bad", "boom")]
    assert events == [("bad", "sell"), ("good", "sell"), ("good", "buy")]
    assert sleep_calls == [1, 1, 1, 1, 1]
