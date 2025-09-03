"""Tests for price lookup within the rebalance workflow."""

from __future__ import annotations

import argparse
import asyncio
from types import SimpleNamespace

import pytest

from src import rebalance
from src.core.pricing import PricingError


def _setup_common(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Prepare common patches and return a dict to capture prices."""

    cfg = SimpleNamespace(
        ibkr=SimpleNamespace(host="h", port=1, client_id=1, account_id="a"),
        models=SimpleNamespace(smurf=0.5, badass=0.3, gltr=0.2),
        pricing=SimpleNamespace(price_source="last", fallback_to_snapshot=True),
    )
    monkeypatch.setattr(rebalance, "load_config", lambda _: cfg)

    async def fake_load_portfolios(path, *, host, port, client_id):
        return {
            "AAA": {"smurf": 0.5, "badass": 0.3, "gltr": 0.2},
            "BBB": {"smurf": 0.5, "badass": 0.3, "gltr": 0.2},
        }

    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)

    class FakeClient:
        def __init__(self) -> None:
            self._ib = object()

        async def connect(self, host, port, client_id):  # pragma: no cover - trivial
            return None

        async def disconnect(self, host, port, client_id):  # pragma: no cover
            return None

        async def snapshot(self, account_id):
            return {
                "positions": [{"symbol": "AAA", "position": 1, "avg_cost": 10.0}],
                "cash": 100.0,
                "net_liq": 110.0,
            }

    monkeypatch.setattr(rebalance, "IBKRClient", lambda: FakeClient())

    captured: dict[str, float] = {}

    def fake_compute_drift(current, targets, prices, net_liq, cfg):
        captured.update(prices)
        return {}

    monkeypatch.setattr(rebalance, "compute_drift", fake_compute_drift)
    monkeypatch.setattr(rebalance, "prioritize_by_drift", lambda drifts, cfg: [])
    monkeypatch.setattr(
        rebalance, "size_orders", lambda prioritized, prices, cash, cfg: ([], [], [])
    )
    monkeypatch.setattr(rebalance, "render_preview", lambda *args, **kwargs: "TABLE")

    return captured


def test_run_fetches_prices_for_all_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    captured = _setup_common(monkeypatch)

    async def fake_fetch_price(ib, symbol, cfg):
        return symbol, {"AAA": 15.0, "BBB": 20.0}[symbol]

    monkeypatch.setattr(rebalance, "_fetch_price", fake_fetch_price)

    args = argparse.Namespace(
        config="cfg", csv="csv", dry_run=True, yes=False, read_only=False
    )
    asyncio.run(rebalance._run(args))

    assert captured == {"AAA": 15.0, "BBB": 20.0}


def test_run_aborts_when_price_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    captured = _setup_common(monkeypatch)

    async def fake_fetch_price(ib, symbol, cfg):
        raise PricingError("bad price")

    monkeypatch.setattr(rebalance, "_fetch_price", fake_fetch_price)

    args = argparse.Namespace(
        config="cfg", csv="csv", dry_run=True, yes=False, read_only=False
    )
    with pytest.raises(SystemExit):
        asyncio.run(rebalance._run(args))

    out, _ = capsys.readouterr()
    assert "bad price" in out
    assert captured == {}
