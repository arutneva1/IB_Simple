import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.io.portfolio_csv import PortfolioCSVError, load_portfolios


def test_load_portfolios_valid(tmp_path: Path) -> None:
    content = """ETF,SMURF,BADASS,GLTR
BLOK,50%,,0%
SPY,,25%,50%
"""
    path = tmp_path / "pf.csv"
    path.write_text(content)
    portfolios = load_portfolios(path)
    assert portfolios == {
        "BLOK": {"smurf": 50.0, "badass": 0.0, "gltr": 0.0},
        "SPY": {"smurf": 0.0, "badass": 25.0, "gltr": 50.0},
    }


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
