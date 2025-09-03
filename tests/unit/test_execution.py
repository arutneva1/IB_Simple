import asyncio
import csv
import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from src.broker.execution import submit_batch
from src.broker.ibkr_client import IBKRError
from src.core.drift import Drift
from src.core.sizing import SizedTrade
from src.io.reporting import write_post_trade_report


class AwaitableEvent(asyncio.Event):
    def __await__(self):  # type: ignore[override]
        return self.wait().__await__()


class DummyTrade:
    def __init__(self, status="Submitted", filled=0.0):
        self.orderStatus = SimpleNamespace(
            status=status, filled=filled, avgFillPrice=0.0
        )
        self.order = SimpleNamespace(orderId=1)
        self.statusEvent = AwaitableEvent()


class DummyTradeWithCommission(DummyTrade):
    def __init__(self, status: str = "Submitted", filled: float = 0.0):
        super().__init__(status=status, filled=filled)
        self.fills: list[Any] = []
        self.commissionReportEvent = AwaitableEvent()


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
        execution=SimpleNamespace(
            algo_preference="none",
            fallback_plain_market=False,
            commission_report_timeout=0.01,
        ),
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
            "fill_qty": 0.0,
            "fill_price": 0.0,
            "fill_time": None,
            "commission": 0.0,
            "commission_placeholder": False,
        }
    ]


def test_partial_fill_reports_final_quantity(monkeypatch, caplog):
    """Partial fill updates are reflected in final result and logged."""
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
    caplog.set_level(logging.INFO)
    res = asyncio.run(submit_batch(client, [trade], cfg))
    assert res[0]["status"] == "Filled"
    assert res[0]["filled"] == pytest.approx(10.0)
    messages = "\n".join(r.message for r in caplog.records)
    assert "transitioned to PartiallyFilled" in messages
    assert "transitioned to Filled" in messages


def test_algo_order_falls_back_to_plain_market(monkeypatch):
    """Algorithmic orders retry as plain market orders on failure."""
    ib = SimpleNamespace()
    monkeypatch.setattr(ib, "reqCurrentTimeAsync", _time_within_rth, raising=False)

    events: list[str] = []

    def fake_place(*_a, **_k):
        if not events:
            events.append("algo")
            return DummyTrade(status="Rejected")
        events.append("plain")
        return DummyTrade(status="Filled", filled=1.0)

    def fake_cancel(_order):
        events.append("cancel")

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    monkeypatch.setattr(ib, "cancelOrder", fake_cancel, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 1.0, 1.0)
    cfg = _base_cfg()
    cfg.execution.algo_preference = "midprice"
    cfg.execution.fallback_plain_market = True
    res = asyncio.run(submit_batch(client, [trade], cfg))
    assert res[0]["status"] == "Filled"
    assert res[0]["filled"] == pytest.approx(1.0)
    assert events == ["algo", "cancel", "plain"]


def test_submit_batch_merges_duplicate_trades(monkeypatch):
    """Duplicate trades for the same symbol/action collapse into one order."""
    ib = SimpleNamespace()
    monkeypatch.setattr(ib, "reqCurrentTimeAsync", _time_within_rth, raising=False)

    calls = []

    def fake_place(_contract, order):
        calls.append(order.totalQuantity)
        return DummyTrade(status="Filled", filled=order.totalQuantity)

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trades = [
        SizedTrade("AAA", "BUY", 1.0, 1.0),
        SizedTrade("AAA", "BUY", 2.0, 2.0),
    ]
    cfg = _base_cfg()

    res = asyncio.run(submit_batch(client, trades, cfg))

    assert len(res) == 1
    assert calls == [3.0]


def test_rth_guard_raises_outside_hours(monkeypatch):
    ib = SimpleNamespace()
    monkeypatch.setattr(ib, "reqCurrentTimeAsync", _time_outside_rth, raising=False)
    client = FakeClient(ib)
    cfg = _base_cfg(prefer_rth=True)
    with pytest.raises(IBKRError):
        asyncio.run(submit_batch(client, [], cfg))


def test_delayed_commission_reports_recorded(monkeypatch, tmp_path):
    """Multiple fills with delayed commission reports are summed correctly."""
    ib = SimpleNamespace()
    monkeypatch.setattr(ib, "reqCurrentTimeAsync", _time_within_rth, raising=False)

    def fake_place(*_a, **_k):
        trade = DummyTradeWithCommission()

        async def updates() -> None:
            fill1 = SimpleNamespace(
                execution=SimpleNamespace(
                    time=datetime(2023, 1, 1, tzinfo=ZoneInfo("UTC"))
                ),
                commissionReport=None,
            )
            fill2 = SimpleNamespace(
                execution=SimpleNamespace(
                    time=datetime(2023, 1, 1, 0, 1, tzinfo=ZoneInfo("UTC"))
                ),
                commissionReport=None,
            )
            trade.fills.extend([fill1, fill2])
            trade.orderStatus.status = "Filled"
            trade.orderStatus.filled = 10.0
            trade.statusEvent.set()
            await asyncio.sleep(0)
            fill1.commissionReport = SimpleNamespace(commission=-0.5)
            fill2.commissionReport = SimpleNamespace(commission=-0.7)
            trade.commissionReportEvent.set()

        asyncio.create_task(updates())
        return trade

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    sized_trade = SizedTrade("AAA", "BUY", 10.0, 1000.0)
    cfg = SimpleNamespace(
        rebalance=SimpleNamespace(prefer_rth=False),
        execution=SimpleNamespace(
            algo_preference="none",
            fallback_plain_market=False,
            order_type="MKT",
            commission_report_timeout=0.01,
        ),
    )

    res = asyncio.run(submit_batch(client, [sized_trade], cfg))
    assert res[0]["commission"] == pytest.approx(1.2)

    drift = Drift("AAA", 60.0, 50.0, -10.0, -1000.0, "BUY")
    ts = datetime(2023, 1, 1)
    post_path = write_post_trade_report(
        tmp_path,
        ts,
        "ACCT",
        [drift],
        [sized_trade],
        res,
        9000.0,
        0.9,
        10000.0,
        1.0,
        cfg,
    )
    with post_path.open() as f:
        row = next(csv.DictReader(f))
    assert float(row["commission"]) == pytest.approx(1.2)


def test_commission_report_arrives_after_initial_wait(monkeypatch):
    """Commission reports arriving after the first wait are included."""

    ib = SimpleNamespace()
    monkeypatch.setattr(ib, "reqCurrentTimeAsync", _time_within_rth, raising=False)

    def fake_place(*_a, **_k):
        trade = DummyTradeWithCommission()

        async def updates() -> None:
            fill1 = SimpleNamespace(
                execution=SimpleNamespace(
                    time=datetime(2023, 1, 1, tzinfo=ZoneInfo("UTC"))
                ),
                commissionReport=None,
            )
            trade.fills.append(fill1)
            trade.orderStatus.status = "Filled"
            trade.orderStatus.filled = 5.0
            trade.statusEvent.set()
            await asyncio.sleep(0)
            fill1.commissionReport = SimpleNamespace(commission=-0.5)
            trade.commissionReportEvent.set()
            await asyncio.sleep(0)
            fill2 = SimpleNamespace(
                execution=SimpleNamespace(
                    time=datetime(2023, 1, 1, 0, 1, tzinfo=ZoneInfo("UTC"))
                ),
                commissionReport=SimpleNamespace(commission=-0.7),
            )
            trade.fills.append(fill2)
            trade.commissionReportEvent.set()

        asyncio.create_task(updates())
        return trade

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 5.0, 500.0)
    cfg = _base_cfg()
    res = asyncio.run(submit_batch(client, [trade], cfg))
    assert res[0]["commission"] == pytest.approx(1.2)


def test_placeholder_commission_logs_warning(monkeypatch, caplog):
    """Placeholder commission reports trigger warning and zero commission."""

    ib = SimpleNamespace()
    monkeypatch.setattr(ib, "reqCurrentTimeAsync", _time_within_rth, raising=False)

    def fake_place(*_a, **_k):
        trade = DummyTradeWithCommission(status="Filled", filled=5.0)
        fill = SimpleNamespace(
            execution=SimpleNamespace(time=datetime(2023, 1, 1, tzinfo=ZoneInfo("UTC"))),
            commissionReport=SimpleNamespace(execId="", commission=0.0),
        )
        trade.fills.append(fill)
        return trade

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 5.0, 500.0)
    cfg = _base_cfg()
    caplog.set_level(logging.WARNING)
    res = asyncio.run(submit_batch(client, [trade], cfg))
    assert res[0]["commission"] == pytest.approx(0.0)
    assert res[0]["commission_placeholder"] is True
    messages = [rec.message for rec in caplog.records]
    assert any("placeholder commission report" in m for m in messages)
