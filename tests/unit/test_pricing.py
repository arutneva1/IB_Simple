import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.pricing import PricingError, get_price


class Ticker(SimpleNamespace):
    """Simple ticker object used for stubbing responses."""


def test_get_price_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Live price is returned when available and snapshot is disabled."""

    ib = SimpleNamespace()
    calls = []

    async def fake_req(contract, *, snapshot: bool = False):
        calls.append(snapshot)
        return [Ticker(last=100.0)]

    monkeypatch.setattr(ib, "reqTickersAsync", fake_req, raising=False)

    price = asyncio.run(
        get_price(ib, "AAPL", price_source="last", fallback_to_snapshot=False)
    )

    assert price == 100.0
    assert calls == [False]


def test_get_price_falls_back_to_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot price is used when live price is missing and fallback enabled."""

    ib = SimpleNamespace()
    calls = []

    async def fake_req(contract, *, snapshot: bool = False):
        calls.append(snapshot)
        if snapshot:
            return [Ticker(last=50.0)]
        return [Ticker(last=None)]

    monkeypatch.setattr(ib, "reqTickersAsync", fake_req, raising=False)

    price = asyncio.run(
        get_price(ib, "AAPL", price_source="last", fallback_to_snapshot=True)
    )

    assert price == 50.0
    assert calls == [False, True]


def test_get_price_raises_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """PricingError is raised when both live and snapshot prices are missing."""

    ib = SimpleNamespace()
    calls = []

    async def fake_req(contract, *, snapshot: bool = False):
        calls.append(snapshot)
        return [Ticker(last=None)]

    monkeypatch.setattr(ib, "reqTickersAsync", fake_req, raising=False)

    with pytest.raises(PricingError):
        asyncio.run(
            get_price(ib, "AAPL", price_source="last", fallback_to_snapshot=True)
        )

    assert calls == [False, True]
