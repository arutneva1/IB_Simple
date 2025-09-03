import argparse
import asyncio
from types import SimpleNamespace

import pytest

from src import rebalance
from src.core.sizing import SizedTrade


def _setup_common(monkeypatch: pytest.MonkeyPatch):
    cfg = SimpleNamespace(
        ibkr=SimpleNamespace(host="h", port=1, client_id=1, account_id="a", read_only=False),
        models=SimpleNamespace(smurf=0.5, badass=0.3, gltr=0.2),
        pricing=SimpleNamespace(price_source="last", fallback_to_snapshot=True),
        rebalance=SimpleNamespace(min_order_usd=1, allow_fractional=True, cash_buffer_pct=0, max_leverage=2),
        execution=SimpleNamespace(algo_preference="adaptive", fallback_plain_market=False),
    )
    monkeypatch.setattr(rebalance, "load_config", lambda _: cfg)

    async def fake_load_portfolios(path, *, host, port, client_id):
        return {"AAA": {"smurf": 1.0, "badass": 0.0, "gltr": 0.0}}

    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)

    class FakeClient:
        def __init__(self):
            self._ib = object()

        async def connect(self, host, port, client_id):
            return None

        async def disconnect(self, host, port, client_id):
            return None

        async def snapshot(self, account_id):
            return {"positions": [], "cash": 100.0, "net_liq": 100.0}

    monkeypatch.setattr(rebalance, "IBKRClient", lambda: FakeClient())

    async def fake_get_price(ib, symbol, *, price_source, fallback_to_snapshot):
        return 10.0

    monkeypatch.setattr(rebalance, "get_price", fake_get_price)

    monkeypatch.setattr(rebalance, "compute_drift", lambda *a, **k: [])
    monkeypatch.setattr(rebalance, "prioritize_by_drift", lambda drifts, cfg: [])
    monkeypatch.setattr(
        rebalance,
        "size_orders",
        lambda prioritized, prices, cash, cfg: ([SizedTrade("AAA", "BUY", 5.0, 50.0)], 0.0, 0.0),
    )
    monkeypatch.setattr(rebalance, "render_preview", lambda *a, **k: "TABLE")

    return cfg


def test_run_submits_orders_and_prints_summary(monkeypatch, capsys):
    _setup_common(monkeypatch)
    recorded = {}

    async def fake_submit_batch(client, trades, cfg):
        recorded["trades"] = trades
        return [{"symbol": "AAA", "status": "Filled", "filled": 5.0, "avg_fill_price": 10.0}]

    monkeypatch.setattr(rebalance, "submit_batch", fake_submit_batch)

    args = argparse.Namespace(config="cfg", csv="csv", dry_run=False, yes=True, read_only=False)
    asyncio.run(rebalance._run(args))

    assert recorded["trades"] == [{"symbol": "AAA", "action": "BUY", "quantity": 5.0}]
    out, _ = capsys.readouterr()
    assert "AAA" in out and "Filled" in out


def test_run_raises_on_order_failure(monkeypatch):
    _setup_common(monkeypatch)

    async def fake_submit_batch(client, trades, cfg):
        return [{"symbol": "AAA", "status": "Rejected", "filled": 0.0, "avg_fill_price": 0.0}]

    monkeypatch.setattr(rebalance, "submit_batch", fake_submit_batch)

    args = argparse.Namespace(config="cfg", csv="csv", dry_run=False, yes=True, read_only=False)
    with pytest.raises(SystemExit):
        asyncio.run(rebalance._run(args))
