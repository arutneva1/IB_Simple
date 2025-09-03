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

    async def reqContractDetailsAsync(self, contract):
        self.calls.append(contract.symbol)
        detail = self.mapping.get(contract.symbol)
        return [detail] if detail else []

    async def connectAsync(
        self, host, port, clientId
    ):  # noqa: N803 (upstream uses camelCase)
        self.connected = True

    def disconnect(self):
        self.connected = False


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


def test_validate_symbols_unknown(monkeypatch) -> None:
    ib = setup_fake_ib(monkeypatch)
    with pytest.raises(PortfolioCSVError):
        asyncio.run(
            portfolio_csv.validate_symbols(
                ["BLOK", "BAD"], host="127.0.0.1", port=4001, client_id=1
            )
        )
    assert ib.calls == ["BLOK", "BAD"]


def test_validate_symbols_skips_cash(monkeypatch) -> None:
    ib = setup_fake_ib(monkeypatch)
    asyncio.run(
        portfolio_csv.validate_symbols(
            ["CASH", "SPY"], host="127.0.0.1", port=4001, client_id=1
        )
    )
    assert ib.calls == ["SPY"]
