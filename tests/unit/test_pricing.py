import asyncio
from types import SimpleNamespace

import pytest

from src.core.pricing import PricingError, get_price


class FakeIB:
    def __init__(self, *responses):
        # responses is a list of lists of ticker objects
        self.responses = list(responses)
        self.calls = []

    async def reqTickersAsync(
        self, contract, *, snapshot=False
    ):  # pragma: no cover - simple stub
        self.calls.append(snapshot)
        return self.responses.pop(0)


class Ticker(SimpleNamespace):
    pass


def test_get_price_realtime_only():
    ib = FakeIB([Ticker(last=100.0)])
    price = asyncio.run(
        get_price(ib, "AAPL", price_source="last", fallback_to_snapshot=True)
    )
    assert price == 100.0
    assert ib.calls == [False]


def test_get_price_uses_snapshot_when_missing():
    ib = FakeIB([Ticker(last=None)], [Ticker(last=50.0)])
    price = asyncio.run(
        get_price(ib, "AAPL", price_source="last", fallback_to_snapshot=True)
    )
    assert price == 50.0
    assert ib.calls == [False, True]


def test_get_price_raises_when_unavailable():
    ib = FakeIB([Ticker(last=None)])
    with pytest.raises(PricingError):
        asyncio.run(
            get_price(ib, "AAPL", price_source="last", fallback_to_snapshot=False)
        )
    assert ib.calls == [False]
