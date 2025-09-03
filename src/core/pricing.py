"""Utility functions for fetching prices from Interactive Brokers.

This module exposes :func:`get_price` which retrieves a price for a given
symbol using an :class:`ib_async.IB` connection.  The desired price field is
specified via the ``price_source`` argument which maps to an attribute on the
returned ticker.  Common values are ``"last"``, ``"close"``, ``"bid"`` and
``"ask"``.

If the requested field is missing and ``fallback_to_snapshot`` is ``True`` the
function retries the request with ``snapshot=True`` to obtain delayed market
data.  A :class:`PricingError` is raised when no price can be determined.
"""

from __future__ import annotations

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
        requested field, the function performs a second request with
        ``snapshot=True`` to fetch delayed data.  The snapshot is not attempted
        when set to ``False``.

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

    # Initial realtime market data request using the qualified contract
    tickers = await ib.reqTickersAsync(contract)
    price = getattr(tickers[0], price_source, None) if tickers else None

    # If no price and snapshot fallback is enabled, try again with the same
    # qualified contract but requesting delayed snapshot data
    if price is None and fallback_to_snapshot:
        tickers = await ib.reqTickersAsync(contract, snapshot=True)
        price = getattr(tickers[0], price_source, None) if tickers else None

    if price is None:
        raise PricingError(f"No price available for {symbol} using {price_source}")

    return float(price)
