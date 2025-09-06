import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

import src.broker.ibkr_client as ibkr_client
import src.broker.utils as broker_utils
from src.broker.errors import IBKRError
from src.broker.ibkr_client import IBKRClient


class FakeIBSnapshot:
    async def connectAsync(self, host, port, clientId):
        return None

    def disconnect(self):
        pass

    async def reqPositionsAsync(self):
        return [
            SimpleNamespace(
                account="ACC",
                contract=SimpleNamespace(symbol="AAPL", currency="USD"),
                position=10,
                avgCost=100.0,
            ),
            SimpleNamespace(
                account="ACC",
                contract=SimpleNamespace(symbol="SHOP", currency="CAD"),
                position=5,
                avgCost=150.0,
            ),
            SimpleNamespace(
                account="OTHER",
                contract=SimpleNamespace(symbol="MSFT", currency="USD"),
                position=20,
                avgCost=200.0,
            ),
        ]

    async def reqAccountUpdatesAsync(self, account):
        return None

    def portfolio(self):
        return [
            SimpleNamespace(
                account="ACC",
                contract=SimpleNamespace(symbol="AAPL", currency="USD"),
                position=10,
                marketPrice=110.0,
                marketValue=1100.0,
                averageCost=100.0,
            ),
            SimpleNamespace(
                account="ACC",
                contract=SimpleNamespace(symbol="SHOP", currency="CAD"),
                position=5,
                marketPrice=150.0,
                marketValue=750.0,
                averageCost=150.0,
            ),
            SimpleNamespace(
                account="OTHER",
                contract=SimpleNamespace(symbol="MSFT", currency="USD"),
                position=20,
                marketPrice=200.0,
                marketValue=4000.0,
                averageCost=200.0,
            ),
        ]

    async def reqAccountSummaryAsync(self, account_id):
        return None

    async def accountSummaryAsync(self, account_id):
        return [
            SimpleNamespace(tag="CashBalance", value="1000", currency="USD"),
            SimpleNamespace(tag="CashBalance", value="500", currency="CAD"),
            SimpleNamespace(tag="NetLiquidation", value="2000", currency="USD"),
            SimpleNamespace(tag="ExchangeRate", value="0.75", currency="CAD"),
        ]


def test_snapshot_converts_cad_cash(monkeypatch):
    fake_ib = FakeIBSnapshot()
    monkeypatch.setattr(ibkr_client, "IB", lambda: fake_ib)
    client = IBKRClient()
    result = asyncio.run(client.snapshot("ACC"))
    assert result == {
        "positions": [
            {
                "account": "ACC",
                "symbol": "AAPL",
                "position": 10,
                "avg_cost": 100.0,
                "market_price": 110.0,
                "market_value": 1100.0,
            }
        ],
        "cash": 1000.0,
        "net_liq": 1625.0,
    }
    symbols = {p["symbol"] for p in result["positions"]}
    assert "MSFT" not in symbols


class FakeIBSnapshotNoFx(FakeIBSnapshot):
    async def accountSummaryAsync(self, account_id):
        return [
            SimpleNamespace(tag="CashBalance", value="1000", currency="USD"),
            SimpleNamespace(tag="CashBalance", value="500", currency="CAD"),
            SimpleNamespace(tag="NetLiquidation", value="2000", currency="USD"),
        ]


def test_snapshot_cad_cash_no_fx_rate(monkeypatch):
    fake_ib = FakeIBSnapshotNoFx()
    monkeypatch.setattr(ibkr_client, "IB", lambda: fake_ib)
    client = IBKRClient()
    result = asyncio.run(client.snapshot("ACC"))
    assert result == {
        "positions": [
            {
                "account": "ACC",
                "symbol": "AAPL",
                "position": 10,
                "avg_cost": 100.0,
                "market_price": 110.0,
                "market_value": 1100.0,
            }
        ],
        "cash": 1000.0,
        "net_liq": 1500.0,
    }
    symbols = {p["symbol"] for p in result["positions"]}
    assert "MSFT" not in symbols


class FailingIB:
    def __init__(self):
        self.calls = 0

    async def connectAsync(self, host, port, clientId):
        self.calls += 1
        raise RuntimeError("boom")


def test_connect_retry_exhaustion_message(monkeypatch):
    failing_ib = FailingIB()
    monkeypatch.setattr(ibkr_client, "IB", lambda: failing_ib)

    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(broker_utils.asyncio, "sleep", fake_sleep)

    client = IBKRClient()
    with pytest.raises(IBKRError) as exc:
        asyncio.run(client.connect("127.0.0.1", 4002, 1))
    assert "connect to IBKR failed" in str(exc.value)
    assert failing_ib.calls == 3
    assert sleeps == [0.5, 1.0]
