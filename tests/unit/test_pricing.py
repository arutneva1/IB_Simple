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
    qualify_calls: list = []
    req_calls: list = []

    qualified_contract = SimpleNamespace()

    async def fake_qualify(contract):
        qualify_calls.append(contract)
        return [qualified_contract]

    async def fake_req(contract, *, snapshot: bool = False):
        req_calls.append((contract, snapshot))
        return [Ticker(last=100.0)]

    monkeypatch.setattr(ib, "qualifyContractsAsync", fake_qualify, raising=False)
    monkeypatch.setattr(ib, "reqTickersAsync", fake_req, raising=False)

    price = asyncio.run(
        get_price(ib, "AAPL", price_source="last", fallback_to_snapshot=False)
    )

    assert price == 100.0
    assert len(qualify_calls) == 1
    assert req_calls == [(qualified_contract, False)]
    assert getattr(qualify_calls[0], "symbol") == "AAPL"
    assert getattr(qualify_calls[0], "exchange") == "SMART"
    assert getattr(qualify_calls[0], "currency") == "USD"


def test_get_price_falls_back_to_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot price is used when live price is missing and fallback enabled."""

    ib = SimpleNamespace()
    qualify_calls: list = []
    req_calls: list = []

    qualified_contract = SimpleNamespace()

    async def fake_qualify(contract):
        qualify_calls.append(contract)
        return [qualified_contract]

    async def fake_req(contract, *, snapshot: bool = False):
        req_calls.append((contract, snapshot))
        if snapshot:
            return [Ticker(last=50.0)]
        return [Ticker(last=None)]

    monkeypatch.setattr(ib, "qualifyContractsAsync", fake_qualify, raising=False)
    monkeypatch.setattr(ib, "reqTickersAsync", fake_req, raising=False)

    price = asyncio.run(
        get_price(ib, "AAPL", price_source="last", fallback_to_snapshot=True)
    )

    assert price == 50.0
    assert len(qualify_calls) == 1
    assert req_calls == [
        (qualified_contract, False),
        (qualified_contract, True),
    ]
    assert getattr(qualify_calls[0], "symbol") == "AAPL"
    assert getattr(qualify_calls[0], "exchange") == "SMART"
    assert getattr(qualify_calls[0], "currency") == "USD"


def test_get_price_raises_when_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """PricingError is raised when both live and snapshot prices are missing."""

    ib = SimpleNamespace()
    qualify_calls: list = []
    req_calls: list = []

    qualified_contract = SimpleNamespace()

    async def fake_qualify(contract):
        qualify_calls.append(contract)
        return [qualified_contract]

    async def fake_req(contract, *, snapshot: bool = False):
        req_calls.append((contract, snapshot))
        return [Ticker(last=None)]

    monkeypatch.setattr(ib, "qualifyContractsAsync", fake_qualify, raising=False)
    monkeypatch.setattr(ib, "reqTickersAsync", fake_req, raising=False)

    with pytest.raises(PricingError):
        asyncio.run(
            get_price(ib, "AAPL", price_source="last", fallback_to_snapshot=True)
        )

    assert len(qualify_calls) == 1
    assert req_calls == [
        (qualified_contract, False),
        (qualified_contract, True),
    ]
    assert getattr(qualify_calls[0], "symbol") == "AAPL"
    assert getattr(qualify_calls[0], "exchange") == "SMART"
    assert getattr(qualify_calls[0], "currency") == "USD"


def test_get_price_raises_when_contract_not_qualified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PricingError is raised if contract qualification returns nothing."""

    ib = SimpleNamespace()
    qualify_calls: list = []
    req_calls: list = []

    async def fake_qualify(contract):
        qualify_calls.append(contract)
        return []

    async def fake_req(contract, *, snapshot: bool = False):
        req_calls.append((contract, snapshot))
        return [Ticker(last=100.0)]

    monkeypatch.setattr(ib, "qualifyContractsAsync", fake_qualify, raising=False)
    monkeypatch.setattr(ib, "reqTickersAsync", fake_req, raising=False)

    with pytest.raises(PricingError):
        asyncio.run(
            get_price(ib, "AAPL", price_source="last", fallback_to_snapshot=True)
        )

    assert len(qualify_calls) == 1
    assert req_calls == []
