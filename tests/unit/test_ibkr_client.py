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

    async def reqAccountSummaryAsync(self, account_id):
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


class FakeIBContext:
    def __init__(self):
        self.connect_calls = 0
        self.disconnect_calls = 0

    async def connectAsync(self, host, port, clientId):
        self.connect_calls += 1

    def disconnect(self):
        self.disconnect_calls += 1


def test_context_manager_connects_and_disconnects(monkeypatch):
    instances: list[FakeIBContext] = []

    def fake_ib_factory() -> FakeIBContext:
        ib = FakeIBContext()
        instances.append(ib)
        return ib

    monkeypatch.setattr(ibkr_client, "IB", fake_ib_factory)

    client_ids: list[int] = []

    async def run() -> None:
        async with IBKRClient("h", 1, 1) as c1:
            client_ids.append(id(c1))

        try:
            async with IBKRClient("h", 1, 1) as c2:
                client_ids.append(id(c2))
                raise RuntimeError("boom")
        except RuntimeError:
            pass

    asyncio.run(run())

    assert len(instances) == 2
    assert client_ids[0] != client_ids[1]
    for inst in instances:
        assert inst.connect_calls == 1
        assert inst.disconnect_calls == 1
