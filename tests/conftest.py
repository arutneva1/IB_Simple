from pathlib import Path

import pytest


@pytest.fixture
def portfolios_csv_path() -> Path:
    """Path to the default portfolios CSV used in tests."""
    return Path(__file__).resolve().parent.parent / "config" / "portfolios.csv"
