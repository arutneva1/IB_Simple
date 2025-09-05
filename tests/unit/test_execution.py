import asyncio
import csv
import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

import src.broker.utils as broker_utils
from src.broker.errors import IBKRError
from src.broker.execution import submit_batch
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


def _base_cfg(trading_hours: str = "rth"):
    return SimpleNamespace(
        rebalance=SimpleNamespace(trading_hours=trading_hours),
        execution=SimpleNamespace(
            algo_preference="none",
            fallback_plain_market=False,
            commission_report_timeout=0.01,
        ),
    )


def test_rejected_order_returns_status(monkeypatch):
    """Rejected order triggers IBKRError."""
    ib = SimpleNamespace()

    def fake_place(*_a, **_k):
        return DummyTrade(status="Rejected")

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 1.0, 1.0)
    cfg = _base_cfg()
    with pytest.raises(IBKRError):
        asyncio.run(submit_batch(client, [trade], cfg, "DU"))


def test_submit_batch_sets_order_account(monkeypatch):
    """Orders are tagged with the provided account id."""
    ib = SimpleNamespace()

    account_id = "TEST123"

    def fake_place(contract, order):
        assert order.account == account_id
        return DummyTrade(status="Filled", filled=1.0)

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 1.0, 1.0)
    cfg = _base_cfg()
    res = asyncio.run(submit_batch(client, [trade], cfg, account_id))
    assert res[0]["status"] == "Filled"
    assert res[0]["action"] == trade.action


def test_partial_fill_reports_final_quantity(monkeypatch, caplog):
    """Partial fill updates are reflected in final result and logged."""
    ib = SimpleNamespace()

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
    res = asyncio.run(submit_batch(client, [trade], cfg, "DU"))
    assert res[0]["status"] == "Filled"
    assert res[0]["filled"] == pytest.approx(10.0)
    assert res[0]["action"] == trade.action
    messages = "\n".join(r.message for r in caplog.records)
    assert "transitioned to PartiallyFilled" in messages
    assert "transitioned to Filled" in messages


def test_algo_order_falls_back_to_plain_market(monkeypatch):
    """Algorithmic orders retry as plain market orders on failure."""
    ib = SimpleNamespace()

    order_types: list[str] = []
    events: list[str] = []

    def fake_place(_contract, order):
        order_types.append(order.orderType)
        if not events:
            events.append("attempt")
            return DummyTrade(status="Rejected")
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
    res = asyncio.run(submit_batch(client, [trade], cfg, "DU"))
    assert res[0]["status"] == "Filled"
    assert res[0]["filled"] == pytest.approx(1.0)
    assert res[0]["action"] == trade.action
    assert order_types == ["MIDPRICE", "MKT"]
    assert events == ["attempt", "cancel"]


def test_midprice_order_type(monkeypatch):
    """Midprice preference builds a MIDPRICE order."""
    ib = SimpleNamespace()
    order_types: list[str] = []

    def fake_place(_contract, order):
        order_types.append(order.orderType)
        return DummyTrade(status="Filled", filled=1.0)

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 1.0, 1.0)
    cfg = _base_cfg()
    cfg.execution.algo_preference = "midprice"
    res = asyncio.run(submit_batch(client, [trade], cfg, "DU"))
    assert res[0]["status"] == "Filled"
    assert order_types == ["MIDPRICE"]


def test_timeout_without_fallback_cancels_order(monkeypatch):
    """Timed-out orders are cancelled when no fallback is used."""
    ib = SimpleNamespace()
    cancelled = False

    trade = DummyTrade(status="Submitted")

    def fake_place(*_a, **_k):
        return trade

    def fake_cancel(_order):
        nonlocal cancelled
        cancelled = True
        trade.orderStatus.status = "Cancelled"

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    monkeypatch.setattr(ib, "cancelOrder", fake_cancel, raising=False)
    client = FakeClient(ib)
    st = SizedTrade("AAA", "BUY", 1.0, 1.0)
    cfg = _base_cfg()
    cfg.execution.wait_before_fallback = 0.01

    with pytest.raises(IBKRError):
        asyncio.run(submit_batch(client, [st], cfg, "DU"))

    assert cancelled is True


def test_submit_batch_merges_duplicate_trades(monkeypatch):
    """Duplicate trades for the same symbol/action collapse into one order."""
    ib = SimpleNamespace()

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

    res = asyncio.run(submit_batch(client, trades, cfg, "DU"))

    assert len(res) == 1
    assert res[0]["action"] == "BUY"
    assert calls == [3.0]


def test_trading_hours_eth_sets_outside_rth(monkeypatch):
    ib = SimpleNamespace()

    def fake_place(_contract, order):
        assert getattr(order, "outsideRth", False) is True
        return DummyTrade(status="Filled", filled=order.totalQuantity)

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 1.0, 1.0)
    cfg = _base_cfg(trading_hours="eth")
    res = asyncio.run(submit_batch(client, [trade], cfg, "DU"))
    assert res[0]["status"] == "Filled"
    assert res[0]["action"] == trade.action


def test_trading_hours_rth_default(monkeypatch):
    ib = SimpleNamespace()

    def fake_place(_contract, order):
        assert not getattr(order, "outsideRth", False)
        return DummyTrade(status="Filled", filled=order.totalQuantity)

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 1.0, 1.0)
    cfg = _base_cfg(trading_hours="rth")
    res = asyncio.run(submit_batch(client, [trade], cfg, "DU"))
    assert res[0]["status"] == "Filled"
    assert res[0]["action"] == trade.action


def test_delayed_commission_reports_recorded(monkeypatch, tmp_path):
    """Multiple fills with delayed commission reports are summed correctly."""
    ib = SimpleNamespace()

    def fake_place(*_a, **_k):
        trade = DummyTradeWithCommission()

        async def updates() -> None:
            fill1 = SimpleNamespace(
                execution=SimpleNamespace(
                    execId="1", time=datetime(2023, 1, 1, tzinfo=ZoneInfo("UTC"))
                ),
                commissionReport=None,
            )
            fill2 = SimpleNamespace(
                execution=SimpleNamespace(
                    execId="2", time=datetime(2023, 1, 1, 0, 1, tzinfo=ZoneInfo("UTC"))
                ),
                commissionReport=None,
            )
            trade.fills.extend([fill1, fill2])
            trade.orderStatus.status = "Filled"
            trade.orderStatus.filled = 10.0
            trade.statusEvent.set()
            await asyncio.sleep(0)
            fill1.commissionReport = SimpleNamespace(execId="1", commission=-0.5)
            trade.commissionReport = fill1.commissionReport
            trade.commissionReports = [fill1.commissionReport]
            trade.commissionReportEvent.set()
            await asyncio.sleep(0)
            fill2.commissionReport = SimpleNamespace(execId="2", commission=-0.7)
            trade.commissionReport = fill2.commissionReport
            trade.commissionReports.append(fill2.commissionReport)
            trade.commissionReportEvent.set()

        asyncio.create_task(updates())
        return trade

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    sized_trade = SizedTrade("AAA", "BUY", 10.0, 1000.0)
    cfg = SimpleNamespace(
        rebalance=SimpleNamespace(trading_hours="rth"),
        execution=SimpleNamespace(
            algo_preference="none",
            fallback_plain_market=False,
            order_type="MKT",
            commission_report_timeout=0.01,
        ),
    )

    res = asyncio.run(submit_batch(client, [sized_trade], cfg, "DU"))
    assert res[0]["commission"] == pytest.approx(1.2)
    assert res[0]["action"] == sized_trade.action

    drift = Drift("AAA", 60.0, 50.0, -10.0, -1000.0, "BUY")
    ts = datetime(2023, 1, 1)
    post_path = write_post_trade_report(
        tmp_path,
        ts,
        "ACCT",
        [drift],
        [sized_trade],
        res,
        {"AAA": 100.0},
        10000.0,
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

    def fake_place(*_a, **_k):
        trade = DummyTradeWithCommission()

        async def updates() -> None:
            fill1 = SimpleNamespace(
                execution=SimpleNamespace(
                    execId="1", time=datetime(2023, 1, 1, tzinfo=ZoneInfo("UTC"))
                ),
                commissionReport=None,
            )
            trade.fills.append(fill1)
            trade.orderStatus.status = "Filled"
            trade.orderStatus.filled = 5.0
            trade.statusEvent.set()
            await asyncio.sleep(0)
            fill1.commissionReport = SimpleNamespace(execId="1", commission=-0.5)
            trade.commissionReport = fill1.commissionReport
            trade.commissionReports = [fill1.commissionReport]
            trade.commissionReportEvent.set()
            await asyncio.sleep(0)
            fill2 = SimpleNamespace(
                execution=SimpleNamespace(
                    execId="2", time=datetime(2023, 1, 1, 0, 1, tzinfo=ZoneInfo("UTC"))
                ),
                commissionReport=SimpleNamespace(execId="2", commission=-0.7),
            )
            trade.fills.append(fill2)
            trade.commissionReport = fill2.commissionReport
            trade.commissionReports.append(fill2.commissionReport)
            trade.commissionReportEvent.set()

        asyncio.create_task(updates())
        return trade

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 5.0, 500.0)
    cfg = _base_cfg()
    res = asyncio.run(submit_batch(client, [trade], cfg, "DU"))
    assert res[0]["commission"] == pytest.approx(1.2)
    assert res[0]["action"] == trade.action


def test_commission_report_before_wait(monkeypatch, caplog):
    """Reports arriving before the wait loop are captured without warning."""

    ib = SimpleNamespace()

    def fake_place(*_a, **_k):
        trade = DummyTradeWithCommission()

        async def updates() -> None:
            fill = SimpleNamespace(
                execution=SimpleNamespace(
                    execId="1", time=datetime(2023, 1, 1, tzinfo=ZoneInfo("UTC"))
                ),
                commissionReport=None,
            )
            trade.fills.append(fill)
            trade.orderStatus.status = "Filled"
            trade.orderStatus.filled = 5.0
            trade.statusEvent.set()
            fill.commissionReport = SimpleNamespace(execId="1", commission=-0.5)
            trade.commissionReport = fill.commissionReport
            trade.commissionReports = [fill.commissionReport]
            trade.commissionReportEvent.set()

        asyncio.create_task(updates())
        return trade

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 5.0, 500.0)
    cfg = _base_cfg()
    caplog.set_level(logging.WARNING)
    res = asyncio.run(submit_batch(client, [trade], cfg, "DU"))
    assert res[0]["commission"] == pytest.approx(0.5)
    assert res[0]["action"] == trade.action
    warnings = [rec.message for rec in caplog.records if rec.levelno >= logging.WARNING]
    assert not any("No commission report" in msg for msg in warnings)


def test_placeholder_commission_logs_warning(monkeypatch, caplog):
    """Placeholder commission reports trigger warning and zero commission."""

    ib = SimpleNamespace()

    def fake_place(*_a, **_k):
        trade = DummyTradeWithCommission(status="Filled", filled=5.0)
        fill = SimpleNamespace(
            execution=SimpleNamespace(
                execId="1", time=datetime(2023, 1, 1, tzinfo=ZoneInfo("UTC"))
            ),
            commissionReport=SimpleNamespace(execId="", commission=0.0),
        )
        trade.fills.append(fill)
        return trade

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 5.0, 500.0)
    cfg = _base_cfg()
    caplog.set_level(logging.WARNING)
    res = asyncio.run(submit_batch(client, [trade], cfg, "DU"))
    assert res[0]["commission"] == pytest.approx(0.0)
    assert res[0]["commission_placeholder"] is True
    assert res[0]["action"] == trade.action
    messages = [rec.message for rec in caplog.records]
    assert any("No commission report for execId" in m for m in messages)


def test_trade_level_commission_report(monkeypatch):
    """Trade-level commission reports are applied even if fills are placeholders."""

    ib = SimpleNamespace()

    def fake_place(*_a, **_k):
        trade = DummyTradeWithCommission(status="Filled", filled=5.0)
        fill = SimpleNamespace(
            execution=SimpleNamespace(
                execId="1", time=datetime(2023, 1, 1, tzinfo=ZoneInfo("UTC"))
            ),
            commissionReport=SimpleNamespace(execId="", commission=0.0),
        )
        trade.fills.append(fill)

        async def send_report() -> None:
            await asyncio.sleep(0)
            trade.commissionReport = SimpleNamespace(execId="1", commission=-0.5)
            trade.commissionReportEvent.set()

        asyncio.create_task(send_report())
        return trade

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 5.0, 500.0)
    cfg = _base_cfg()
    res = asyncio.run(submit_batch(client, [trade], cfg, "DU"))
    assert res[0]["commission"] == pytest.approx(0.5)
    assert res[0]["commission_placeholder"] is False
    assert res[0]["action"] == trade.action
    assert res[0]["action"] == trade.action


def test_client_level_commission_report(monkeypatch):
    """Commission reports only emitted via client-level event are recorded."""

    ib = SimpleNamespace()
    ib.client = SimpleNamespace(
        commissionReports=[], commissionReportEvent=AwaitableEvent()
    )

    def fake_place(*_a, **_k):
        trade = DummyTradeWithCommission()

        async def updates() -> None:
            fill = SimpleNamespace(
                execution=SimpleNamespace(
                    execId="1", time=datetime(2023, 1, 1, tzinfo=ZoneInfo("UTC"))
                ),
                commissionReport=None,
            )
            trade.fills.append(fill)
            trade.orderStatus.status = "Filled"
            trade.orderStatus.filled = 5.0
            trade.statusEvent.set()
            await asyncio.sleep(0)
            report = SimpleNamespace(execId="1", commission=-0.5)
            ib.client.commissionReports.append(report)
            ib.client.commissionReportEvent.set()

        asyncio.create_task(updates())
        return trade

    monkeypatch.setattr(ib, "placeOrder", fake_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 5.0, 500.0)
    cfg = _base_cfg()
    res = asyncio.run(submit_batch(client, [trade], cfg, "DU"))
    assert res[0]["commission"] == pytest.approx(0.5)
    assert res[0]["commission_placeholder"] is False


def test_submit_order_retries_exhausted(monkeypatch):
    """Failures after all retries raise IBKRError with concise message."""

    ib = SimpleNamespace()

    calls = {"n": 0}

    def failing_place(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(ib, "placeOrder", failing_place, raising=False)
    client = FakeClient(ib)
    trade = SizedTrade("AAA", "BUY", 1.0, 1.0)
    cfg = _base_cfg()

    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(broker_utils.asyncio, "sleep", fake_sleep)

    with pytest.raises(IBKRError) as exc:
        asyncio.run(submit_batch(client, [trade], cfg, "DU"))
    assert "order submission for AAA failed" in str(exc.value)
    assert calls["n"] == 3
    assert sleeps == [0.5, 1.0]
