import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

import src.io.portfolio_csv as portfolio_csv
from src.io.portfolio_csv import PortfolioCSVError, load_portfolios


class FakeIB:
    def __init__(self) -> None:
        from ib_async.contract import ContractDetails, Stock

        self.mapping = {
            "BLOK": ContractDetails(
                contract=Stock("BLOK", currency="USD"), stockType="ETF"
            ),
            "SPY": ContractDetails(
                contract=Stock("SPY", currency="USD"), stockType="ETF"
            ),
        }

    def reqContractDetails(self, contract):
        symbol = contract.symbol
        detail = self.mapping.get(symbol)
        return [detail] if detail else []


@pytest.fixture(autouse=True)
def fake_ib(monkeypatch):
    ib = FakeIB()
    monkeypatch.setattr(portfolio_csv, "IB", lambda: ib)
    return ib


def test_load_portfolios_valid(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR
BLOK,50%,,0%
SPY,,25%,50%
CASH,50%,75%,50%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    portfolios = load_portfolios(path)
    assert portfolios == {
        "BLOK": {"smurf": 50.0, "badass": 0.0, "gltr": 0.0},
        "SPY": {"smurf": 0.0, "badass": 25.0, "gltr": 50.0},
        "CASH": {"smurf": 50.0, "badass": 75.0, "gltr": 50.0},
    }


def test_totals_without_cash(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR
BLOK,50%,,0%
SPY,,25%,50%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    with pytest.raises(PortfolioCSVError):
        load_portfolios(path)


def test_negative_cash(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR
BLOK,60%,,60%
SPY,50%,25%,50%
CASH,-10%,75%,-10%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    portfolios = load_portfolios(path)
    assert portfolios["CASH"]["smurf"] == -10.0


def test_cash_mismatch(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR
BLOK,50%,,0%
SPY,,25%,50%
CASH,40%,70%,30%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    with pytest.raises(PortfolioCSVError):
        load_portfolios(path)


def test_unknown_column(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR,FOO
BLOK,0%,0%,0%,0%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    with pytest.raises(PortfolioCSVError):
        load_portfolios(path)


def test_duplicate_column(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,SMURF
BLOK,0%,0%,0%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    with pytest.raises(PortfolioCSVError):
        load_portfolios(path)


def test_malformed_percent(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR
BLOK,abc,0%,0%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    with pytest.raises(PortfolioCSVError):
        load_portfolios(path)


def test_unknown_symbol(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR
FAKE,50%,50%,50%
CASH,50%,50%,50%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    with pytest.raises(PortfolioCSVError):
        load_portfolios(path)
