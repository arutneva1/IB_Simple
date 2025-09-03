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
        ]

    async def reqAccountSummaryAsync(self):
        return None

    async def accountSummaryAsync(self, account_id):
        return [
            SimpleNamespace(tag="CashBalance", value="1000", currency="USD"),
            SimpleNamespace(tag="CashBalance", value="500", currency="CAD"),
            SimpleNamespace(tag="NetLiquidation", value="2000", currency="USD"),
        ]


def test_snapshot_filters_cad_cash(monkeypatch):
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
            }
        ],
        "cash": 1000.0,
        "net_liq": 1500.0,
    }


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
