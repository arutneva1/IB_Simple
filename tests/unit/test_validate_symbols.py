import asyncio
import sys
from pathlib import Path

import pytest
from ib_async.contract import ContractDetails, Stock

sys.path.append(str(Path(__file__).resolve().parents[2]))

import src.io.portfolio_csv as portfolio_csv
from src.io.portfolio_csv import PortfolioCSVError


class FakeIB:
    def __init__(self) -> None:
        self.mapping = {
            "BLOK": ContractDetails(
                contract=Stock("BLOK", currency="USD"), stockType="ETF"
            ),
            "SPY": ContractDetails(
                contract=Stock("SPY", currency="USD"), stockType="ETF"
            ),
        }
        self.calls: list[str] = []
        self.connected: bool = False
        self.disconnects: int = 0
        self.raise_disconnect: bool = False

    async def reqContractDetailsAsync(self, contract):
        self.calls.append(contract.symbol)
        detail = self.mapping.get(contract.symbol)
        return [detail] if detail else []

    async def connectAsync(
        self, host, port, clientId
    ):  # noqa: N803 (upstream uses camelCase)
        self.connected = True

    def disconnect(self):
        self.disconnects += 1
        self.connected = False
        if self.raise_disconnect:
            raise RuntimeError("disconnect failed")


def setup_fake_ib(monkeypatch) -> FakeIB:
    ib = FakeIB()
    monkeypatch.setattr(portfolio_csv, "IB", lambda: ib)
    return ib


def test_validate_symbols_valid(monkeypatch) -> None:
    ib = setup_fake_ib(monkeypatch)
    asyncio.run(
        portfolio_csv.validate_symbols(
            ["BLOK", "SPY"], host="127.0.0.1", port=4001, client_id=1
        )
    )
    assert ib.calls == ["BLOK", "SPY"]
    assert ib.disconnects == 1


def test_validate_symbols_unknown(monkeypatch) -> None:
    ib = setup_fake_ib(monkeypatch)
    with pytest.raises(PortfolioCSVError):
        asyncio.run(
            portfolio_csv.validate_symbols(
                ["BLOK", "BAD"], host="127.0.0.1", port=4001, client_id=1
            )
        )
    assert ib.calls == ["BLOK", "BAD"]
    assert ib.disconnects == 1


def test_validate_symbols_skips_cash(monkeypatch) -> None:
    ib = setup_fake_ib(monkeypatch)
    asyncio.run(
        portfolio_csv.validate_symbols(
            ["CASH", "SPY"], host="127.0.0.1", port=4001, client_id=1
        )
    )
    assert ib.calls == ["SPY"]
    assert ib.disconnects == 1


def test_disconnect_error_suppressed(monkeypatch) -> None:
    ib = setup_fake_ib(monkeypatch)
    ib.raise_disconnect = True
    asyncio.run(
        portfolio_csv.validate_symbols(
            ["SPY"], host="127.0.0.1", port=4001, client_id=1
        )
    )
    assert ib.calls == ["SPY"]
    assert ib.disconnects == 1


def test_connection_failure(monkeypatch) -> None:
    ib = setup_fake_ib(monkeypatch)

    async def fail_connect(host, port, clientId):  # noqa: N803 - mimics upstream
        raise OSError("boom")

    setattr(ib, "connectAsync", fail_connect)
    with pytest.raises(PortfolioCSVError) as excinfo:
        asyncio.run(
            portfolio_csv.validate_symbols(
                ["SPY"], host="127.0.0.1", port=4001, client_id=1
            )
        )
    assert "IB connection failed: boom" in str(excinfo.value)
    assert ib.calls == []
    assert ib.disconnects == 1
