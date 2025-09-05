import asyncio
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

import src.io.portfolio_csv as portfolio_csv
import src.rebalance as rebalance
from src.broker.errors import IBKRError

pytestmark = pytest.mark.integration


class DummyIBKRClient:
    """Stub IBKR client for dry-run tests."""

    def __init__(self) -> None:
        self._ib = None

    async def connect(
        self, host: str, port: int, client_id: int
    ) -> None:  # noqa: ARG002
        pass

    async def disconnect(
        self, host: str, port: int, client_id: int
    ) -> None:  # noqa: ARG002
        pass

    async def snapshot(self, account_id: str) -> dict:  # noqa: ARG002
        if account_id == "DUFAIL":
            raise IBKRError("snapshot failed")
        return {
            "positions": [
                {"symbol": "SPY", "position": 10, "avg_cost": 100.0},
                {"symbol": "IAU", "position": 5, "avg_cost": 100.0},
            ],
            "cash": 1000.0,
            "net_liq": 2500.0,
        }


async def fake_fetch_price(ib, symbol, cfg):  # noqa: ARG001
    return symbol, 100.0


async def fake_validate_symbols(symbols, host, port, client_id):  # noqa: ARG001, D401
    return None


def test_rebalance_dry_run(monkeypatch, capsys, portfolios_csv_path):
    monkeypatch.setattr(rebalance, "IBKRClient", DummyIBKRClient)
    monkeypatch.setattr(rebalance, "_fetch_price", fake_fetch_price)
    monkeypatch.setattr(portfolio_csv, "validate_symbols", fake_validate_symbols)

    args = Namespace(
        config="config/settings.ini",
        csv=str(portfolios_csv_path),
        dry_run=True,
        yes=False,
        read_only=False,
    )

    asyncio.run(rebalance._run(args))

    captured = capsys.readouterr().out
    assert "Symbol" in captured
    assert "Batch Summary" in captured
    assert "Dry run complete (no orders submitted)." in captured
    assert "Proceed?" not in captured


def test_rebalance_multiple_accounts_failure(monkeypatch, capsys, portfolios_csv_path):
    monkeypatch.setattr(rebalance, "IBKRClient", DummyIBKRClient)
    monkeypatch.setattr(rebalance, "_fetch_price", fake_fetch_price)
    monkeypatch.setattr(portfolio_csv, "validate_symbols", fake_validate_symbols)

    original_load_config = rebalance.load_config

    def fake_load_config(path):
        cfg = original_load_config(path)
        cfg.accounts.ids = ["DU111111", "DUFAIL", "DU222222"]
        return cfg

    monkeypatch.setattr(rebalance, "load_config", fake_load_config)

    args = Namespace(
        config="config/settings.ini",
        csv=str(portfolios_csv_path),
        dry_run=True,
        yes=False,
        read_only=False,
    )

    failures = asyncio.run(rebalance._run(args))

    captured = capsys.readouterr().out
    assert "DU111111" in captured
    assert "DU222222" in captured
    assert failures and failures[0][0] == "DUFAIL"
