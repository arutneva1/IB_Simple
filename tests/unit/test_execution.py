import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from src.broker.execution import submit_batch
from src.broker.ibkr_client import IBKRError
from src.core.sizing import SizedTrade


class AutoEvent(asyncio.Event):
    async def _wait(self) -> None:
        await super().wait()
        self.clear()

    def __await__(self):  # type: ignore[override]
        return self._wait().__await__()


class DummyTrade:
    def __init__(self, status="Submitted", filled=0.0):
        self.orderStatus = SimpleNamespace(
            status=status, filled=filled, avgFillPrice=0.0
        )
        self.order = SimpleNamespace(orderId=1)
        self.statusEvent = AutoEvent()


class FakeClient:
    def __init__(self, ib):
        self._ib = ib


async def _time_within_rth():
    return datetime(2023, 1, 2, 15, 0, tzinfo=ZoneInfo("UTC"))  # 10:00 NY


async def _time_outside_rth():
    return datetime(2023, 1, 2, 13, 0, tzinfo=ZoneInfo("UTC"))  # 08:00 NY


def _base_cfg(prefer_rth=False):
    return SimpleNamespace(
        rebalance=SimpleNamespace(prefer_rth=prefer_rth),
        execution=SimpleNamespace(algo_preference="none", fallback_plain_market=False),
    )


def test_rejected_order_returns_status(monkeypatch):
    """Rejected order path returns status 'Rejected'."""
    ib = SimpleNamespace()
    monkeypatch.setattr(ib, "reqCurrentTimeAsync", _time_within_rth, raising=False)

    def fake_place(*_a, **_k):
        return DummyTrade(status="Rejected")

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 1.0, 1.0)
    cfg = _base_cfg()
    res = asyncio.run(submit_batch(client, [trade], cfg))
    assert res == [
        {
            "symbol": "AAA",
            "order_id": 1,
            "status": "Rejected",
            "filled": 0.0,
            "avg_fill_price": 0.0,
        }
    ]


def test_partial_fill_reports_final_quantity(monkeypatch):
    """Partial fill updates are reflected in final result."""
    ib = SimpleNamespace()
    monkeypatch.setattr(ib, "reqCurrentTimeAsync", _time_within_rth, raising=False)

    def fake_place(*_a, **_k):
        trade = DummyTrade(status="Submitted")

        async def updates():
            await asyncio.sleep(0)
            trade.orderStatus.status = "PartiallyFilled"
            trade.orderStatus.filled = 5.0
            trade.statusEvent.set()
            await asyncio.sleep(0)
            trade.orderStatus.status = "Filled"
            trade.orderStatus.filled = 10.0
            trade.statusEvent.set()

        asyncio.create_task(updates())
        return trade

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 10.0, 100.0)
    cfg = _base_cfg()
    res = asyncio.run(submit_batch(client, [trade], cfg))
    assert res[0]["status"] == "Filled"
    assert res[0]["filled"] == pytest.approx(10.0)


def test_algo_order_falls_back_to_plain_market(monkeypatch):
    """Algorithmic orders retry as plain market orders on failure."""
    ib = SimpleNamespace()
    monkeypatch.setattr(ib, "reqCurrentTimeAsync", _time_within_rth, raising=False)

    calls = {"count": 0}

    def fake_place(*_a, **_k):
        if calls["count"] == 0:
            calls["count"] += 1
            return DummyTrade(status="Rejected")
        calls["count"] += 1
        return DummyTrade(status="Filled", filled=1.0)

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 1.0, 1.0)
    cfg = _base_cfg()
    cfg.execution.algo_preference = "midprice"
    cfg.execution.fallback_plain_market = True
    res = asyncio.run(submit_batch(client, [trade], cfg))
    assert res[0]["status"] == "Filled"
    assert res[0]["filled"] == pytest.approx(1.0)
    assert calls["count"] == 2


def test_rth_guard_raises_outside_hours(monkeypatch):
    ib = SimpleNamespace()
    monkeypatch.setattr(ib, "reqCurrentTimeAsync", _time_outside_rth, raising=False)
    client = FakeClient(ib)
    cfg = _base_cfg(prefer_rth=True)
    with pytest.raises(IBKRError):
        asyncio.run(submit_batch(client, [], cfg))
