from __future__ import annotations

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
