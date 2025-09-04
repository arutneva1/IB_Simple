"""Integration tests for confirmation prompting behavior."""

from __future__ import annotations

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
    """Stub IBKR client for confirmation tests."""

    def __init__(self) -> None:
        self._ib = None

    async def connect(
        self, host: str, port: int, client_id: int
    ) -> None:  # noqa: ARG002
        return None

    async def disconnect(
        self, host: str, port: int, client_id: int
    ) -> None:  # noqa: ARG002
        return None

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


async def fake_validate_symbols(symbols, host, port, client_id):  # noqa: ARG001, D401
    return None


def test_prompt_default(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Default execution prompts and aborts when the user declines."""

    monkeypatch.setattr(rebalance, "IBKRClient", DummyIBKRClient)
    monkeypatch.setattr(rebalance, "_fetch_price", fake_fetch_price)
    monkeypatch.setattr(portfolio_csv, "validate_symbols", fake_validate_symbols)

    def fake_input(prompt: str) -> str:  # pragma: no cover - trivial
        print(prompt, end="")
        return "n"

    monkeypatch.setattr("builtins.input", fake_input)

    args = Namespace(
        config="config/settings.ini",
        csv="data/portfolios.csv",
        dry_run=False,
        yes=False,
        read_only=False,
    )

    asyncio.run(rebalance._run(args))

    captured = capsys.readouterr().out
    assert "Proceed? [y/N]" in captured
    assert "Aborted by user." in captured


def test_yes_skips_prompt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The --yes flag suppresses the prompt and proceeds."""

    monkeypatch.setattr(rebalance, "IBKRClient", DummyIBKRClient)
    monkeypatch.setattr(rebalance, "_fetch_price", fake_fetch_price)
    monkeypatch.setattr(portfolio_csv, "validate_symbols", fake_validate_symbols)

    def fail_input(*args, **kwargs) -> str:  # pragma: no cover - should not be called
        raise AssertionError("input() should not be invoked when --yes is used")

    monkeypatch.setattr("builtins.input", fail_input)

    async def fake_submit_batch(client, trades, cfg, account_id):  # noqa: ARG001
        return [
            {
                "symbol": t.symbol,
                "status": "Filled",
                "filled": t.quantity,
                "avg_fill_price": 0.0,
            }
            for t in trades
        ]

    monkeypatch.setattr(rebalance, "submit_batch", fake_submit_batch)

    args = Namespace(
        config="config/settings.ini",
        csv="data/portfolios.csv",
        dry_run=False,
        yes=True,
        read_only=False,
    )

    asyncio.run(rebalance._run(args))

    captured = capsys.readouterr().out
    assert "Proceed? [y/N]" not in captured
    assert "Submitting batch market orders" in captured


def test_prompt_global(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Global confirmation prompts once for all accounts."""

    monkeypatch.setattr(rebalance, "IBKRClient", DummyIBKRClient)
    monkeypatch.setattr(rebalance, "_fetch_price", fake_fetch_price)
    monkeypatch.setattr(portfolio_csv, "validate_symbols", fake_validate_symbols)

    prompts: list[str] = []

    def fake_input(prompt: str) -> str:  # pragma: no cover - trivial
        prompts.append(prompt)
        print(prompt, end="")
        return "n"

    monkeypatch.setattr("builtins.input", fake_input)

    args = Namespace(
        config="config/settings.ini",
        csv="data/portfolios.csv",
        dry_run=False,
        yes=False,
        read_only=False,
        confirm_mode="global",
    )

    asyncio.run(rebalance._run(args))

    captured = capsys.readouterr().out
    assert prompts == ["Proceed? [y/N]: "]
    assert "Aborted by user." in captured


def test_yes_skips_prompt_global(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--yes skips the global confirmation prompt."""

    monkeypatch.setattr(rebalance, "IBKRClient", DummyIBKRClient)
    monkeypatch.setattr(rebalance, "_fetch_price", fake_fetch_price)
    monkeypatch.setattr(portfolio_csv, "validate_symbols", fake_validate_symbols)

    def fail_input(*args, **kwargs) -> str:  # pragma: no cover - should not be called
        raise AssertionError("input() should not be invoked when --yes is used")

    monkeypatch.setattr("builtins.input", fail_input)

    async def fake_submit_batch(client, trades, cfg, account_id):  # noqa: ARG001
        return [
            {
                "symbol": t.symbol,
                "status": "Filled",
                "filled": t.quantity,
                "avg_fill_price": 0.0,
            }
            for t in trades
        ]

    monkeypatch.setattr(rebalance, "submit_batch", fake_submit_batch)

    args = Namespace(
        config="config/settings.ini",
        csv="data/portfolios.csv",
        dry_run=False,
        yes=True,
        read_only=False,
        confirm_mode="global",
    )

    asyncio.run(rebalance._run(args))

    captured = capsys.readouterr().out
    assert "Proceed? [y/N]" not in captured
    assert captured.count("Submitting batch market orders") == 2
