import asyncio
import re
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

import src.io.portfolio_csv as portfolio_csv
from src.io.portfolio_csv import PortfolioCSVError, load_portfolios


class FakeIB:
    def __init__(self) -> None:
        from ib_async.contract import ContractDetails, Stock

        symbols = [
            "BLOK",
            "IBIT",
            "ETHA",
            "IAU",
            "GLD",
            "GDX",
            "CWB",
            "BIV",
            "BNDX",
            "VCIT",
            "SCHG",
            "SPY",
            "MGK",
        ]
        self.mapping = {
            s: ContractDetails(contract=Stock(s, currency="USD"), stockType="ETF")
            for s in symbols
        }
        self.connected = False

    async def reqContractDetailsAsync(self, contract):
        detail = self.mapping.get(contract.symbol)
        return [detail] if detail else []

    async def connectAsync(
        self, host, port, clientId
    ):  # noqa: N803 - upstream camelCase
        self.connected = True

    def disconnect(self):
        self.connected = False


@pytest.fixture(autouse=True)
def fake_ib(monkeypatch):
    ib = FakeIB()
    monkeypatch.setattr(portfolio_csv, "IB", lambda: ib)
    return ib


@pytest.fixture()
def portfolios_csv(tmp_path: Path) -> Path:
    src = Path(__file__).resolve().parents[2] / "data" / "portfolios.csv"
    dst = tmp_path / "portfolios.csv"
    dst.write_text(src.read_text())
    return dst


def test_load_portfolios_valid(portfolios_csv: Path) -> None:
    portfolios = asyncio.run(
        load_portfolios(portfolios_csv, host="127.0.0.1", port=4001, client_id=1)
    )
    # there are 14 rows including CASH
    assert len(portfolios) == 14
    assert portfolios["IAU"]["gltr"] == 100.0


def test_positive_cash(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR
BLOK,50%,,0%
SPY,,25%,50%
CASH,50%,75%,50%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    portfolios = asyncio.run(
        load_portfolios(path, host="127.0.0.1", port=4001, client_id=1)
    )
    assert portfolios["CASH"] == {"smurf": 50.0, "badass": 75.0, "gltr": 50.0}


def test_negative_cash(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR
BLOK,60%,,60%
SPY,50%,25%,50%
CASH,-10%,75%,-10%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    portfolios = asyncio.run(
        load_portfolios(path, host="127.0.0.1", port=4001, client_id=1)
    )
    assert portfolios["CASH"]["smurf"] == -10.0


def test_totals_without_cash(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR
BLOK,50%,,0%
SPY,,25%,50%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    msg = r"SMURF: totals 50\.00% do not sum to 100%"
    with pytest.raises(PortfolioCSVError, match=msg):
        asyncio.run(load_portfolios(path, host="127.0.0.1", port=4001, client_id=1))


def test_cash_mismatch(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR
BLOK,50%,,0%
SPY,,25%,50%
CASH,40%,70%,30%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    msg = r"SMURF: assets 50\.00% \+ CASH 40\.00% = 90\.00%, expected 100%"
    with pytest.raises(PortfolioCSVError, match=msg):
        asyncio.run(load_portfolios(path, host="127.0.0.1", port=4001, client_id=1))


def test_unknown_column(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR,FOO
BLOK,0%,0%,0%,0%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    with pytest.raises(PortfolioCSVError, match=r"Unknown columns: FOO"):
        asyncio.run(load_portfolios(path, host="127.0.0.1", port=4001, client_id=1))


def test_duplicate_column(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,SMURF
BLOK,0%,0%,0%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    with pytest.raises(PortfolioCSVError, match=r"Duplicate columns: SMURF"):
        asyncio.run(load_portfolios(path, host="127.0.0.1", port=4001, client_id=1))


@pytest.mark.parametrize(
    "value,expected",
    [
        ("abc", "BLOK: invalid percentage for SMURF: 'abc'"),
        ("200%", "BLOK: percent out of range for SMURF: 200.0"),
    ],
)
def test_malformed_percent(tmp_path: Path, value: str, expected: str) -> None:
    content = f"ETF,SMURF,BADASS,GLTR\nBLOK,{value},0%,0%\n"
    path = tmp_path / "pf.csv"
    path.write_text(content)
    with pytest.raises(PortfolioCSVError, match=re.escape(expected)):
        asyncio.run(load_portfolios(path, host="127.0.0.1", port=4001, client_id=1))


def test_unknown_symbol(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR
FAKE,50%,50%,50%
CASH,50%,50%,50%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    with pytest.raises(PortfolioCSVError, match=r"Unknown ETF symbol: FAKE"):
        asyncio.run(load_portfolios(path, host="127.0.0.1", port=4001, client_id=1))
