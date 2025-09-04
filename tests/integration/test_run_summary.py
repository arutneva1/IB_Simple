import asyncio
import csv
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

import src.io.portfolio_csv as portfolio_csv
import src.rebalance as rebalance

pytestmark = pytest.mark.integration


class DummyIBKRClient:
    """Stub IBKR client for run summary tests."""

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
                {"symbol": "SPY", "position": 10, "avg_cost": 100.0},
                {"symbol": "IAU", "position": 5, "avg_cost": 100.0},
            ],
            "cash": 1000.0,
            "net_liq": 2500.0,
        }


async def fake_fetch_price(ib, symbol, cfg):  # noqa: ARG001
    return symbol, 100.0


async def fake_validate_symbols(symbols, host, port, client_id):  # noqa: ARG001
    return None


def test_run_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(rebalance, "IBKRClient", DummyIBKRClient)
    monkeypatch.setattr(rebalance, "_fetch_price", fake_fetch_price)
    monkeypatch.setattr(portfolio_csv, "validate_symbols", fake_validate_symbols)

    original_load_config = rebalance.load_config

    def fake_load_config(path):
        cfg = original_load_config(path)
        cfg.accounts.ids = ["DU111111", "DU222222"]
        cfg.accounts.pacing_sec = 0
        cfg.io.report_dir = str(tmp_path / "reports")
        return cfg

    monkeypatch.setattr(rebalance, "load_config", fake_load_config)

    args = Namespace(
        config="config/settings.ini",
        csv="data/portfolios.csv",
        dry_run=True,
        yes=False,
        read_only=False,
    )

    asyncio.run(rebalance._run(args))

    report_files = list((tmp_path / "reports").glob("run_summary_*.csv"))
    assert len(report_files) == 1
    with report_files[0].open() as fh:
        rows = list(csv.DictReader(fh))

    assert len(rows) == 2
    statuses = {row["account_id"]: row["status"] for row in rows}
    assert statuses == {"DU111111": "dry_run", "DU222222": "dry_run"}
