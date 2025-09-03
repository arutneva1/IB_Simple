"""Utility functions for fetching prices from Interactive Brokers.

This module exposes :func:`get_price` which retrieves a price for a given
symbol using an :class:`ib_async.IB` connection.  The desired price field is
specified via the ``price_source`` argument which maps to an attribute on the
returned ticker.  Common values are ``"last"``, ``"close"``, ``"bid"`` and
``"ask"``.

If the requested field is missing and ``fallback_to_snapshot`` is ``True`` the
function retries the request with ``snapshot=True`` to obtain delayed market
data.  Additionally when ``price_source`` is ``"last"`` and the last price is
missing or non-finite, the ``"close"`` field is used as a fallback before
resorting to the snapshot request.  A :class:`PricingError` is raised when no
price can be determined.
"""

from __future__ import annotations

import math
from typing import Any

from ib_async.contract import Stock


class PricingError(Exception):
    """Raised when a price cannot be obtained for a symbol."""


async def get_price(
    ib: Any,
    symbol: str,
    *,
    price_source: str,
    fallback_to_snapshot: bool,
) -> float:
    """Return the price for ``symbol`` using market data from IB.

    When ``price_source`` is ``"last"`` and the last price is missing or not a
    finite number, the ``"close"`` price is tried before resorting to the
    optional delayed snapshot request.

    Parameters
    ----------
    ib:
        Connected :class:`ib_async.IB` instance used to request market data.
    symbol:
        Ticker symbol to query (USD stocks or ETFs).
    price_source:
        Name of the price field to extract from the returned ticker.  Typical
        values include ``"last"``, ``"close"``, ``"bid"`` and ``"ask"`` but any
        attribute present on the ticker is supported.
    fallback_to_snapshot:
        When ``True`` and the initial realtime request yields ``None`` for the
        requested field (after the ``"close"`` fallback, if applicable), the
        function performs a second request with ``snapshot=True`` to fetch
        delayed data.  The snapshot is not attempted when set to ``False``.

    Returns
    -------
    float
        The price value extracted from the ticker.

    Raises
    ------
    PricingError
        If no price can be determined after the optional snapshot fallback.
    """

    # Create and qualify the contract to populate ``conId`` and other details
    contract = Stock(symbol=symbol, exchange="SMART", currency="USD")
    qualified_contracts = await ib.qualifyContractsAsync(contract)

    if not qualified_contracts:
        raise PricingError(f"Could not qualify contract for {symbol}")

    contract = qualified_contracts[0]

    def _extract_price(tickers: list[Any], field: str) -> float | None:
        """Return a finite price from ``tickers`` using ``field``.

        When ``field`` is ``"last"`` and the value is missing or non-finite,
        the ``"close"`` field is checked as a secondary source.  ``None`` is
        returned if no suitable value can be found.
        """

        if not tickers:
            return None

        value = getattr(tickers[0], field, None)
        if value is None or not math.isfinite(value):
            if field == "last":
                value = getattr(tickers[0], "close", None)
                if value is None or not math.isfinite(value):
                    return None
            else:
                return None

        return float(value)

    # Initial realtime market data request using the qualified contract
    tickers = await ib.reqTickersAsync(contract)
    price = _extract_price(tickers, price_source)

    # If no price and snapshot fallback is enabled, try again with the same
    # qualified contract but requesting delayed snapshot data
    if price is None and fallback_to_snapshot:
        tickers = await ib.reqTickersAsync(contract, snapshot=True)
        price = _extract_price(tickers, price_source)

    if price is None or not math.isfinite(price):
        raise PricingError(f"Invalid price for {symbol} using {price_source}")

    return price
