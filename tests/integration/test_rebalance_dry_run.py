import asyncio
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

import src.io.portfolio_csv as portfolio_csv
import src.rebalance as rebalance

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
        return {
            "positions": [
                {"symbol": "SPY", "position": 10},
                {"symbol": "IAU", "position": 5},
            ],
            "cash": 1000.0,
            "net_liq": 2500.0,
        }


async def fake_get_price(
    ib, symbol, *, price_source, fallback_to_snapshot
):  # noqa: ARG001
    return 100.0


async def fake_validate_symbols(symbols, host, port, client_id):  # noqa: ARG001, D401
    return None


def test_rebalance_dry_run(monkeypatch, capsys):
    monkeypatch.setattr(rebalance, "IBKRClient", DummyIBKRClient)
    monkeypatch.setattr(rebalance, "get_price", fake_get_price)
    monkeypatch.setattr(portfolio_csv, "validate_symbols", fake_validate_symbols)

    args = Namespace(
        config="config/settings.ini",
        csv="data/portfolios.csv",
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
