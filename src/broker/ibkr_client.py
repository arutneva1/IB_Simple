"""Client abstraction for ``ib_async``.

This module provides a small wrapper around :class:`ib_async.IB` with
exponential-backoff ``connect``/``disconnect`` helpers that raise
``IBKRError`` after repeated failures.  A ``snapshot`` method is also provided
to fetch the current account state in a simplified dictionary form.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict, dataclass
from types import TracebackType
from typing import Any, Awaitable, Callable, Dict, List, cast

from ib_async import IB, Position

from .errors import IBKRError
from .utils import retry_async

log = logging.getLogger(__name__)


@dataclass
class Snapshot:
    """Lightweight container for account snapshot data."""

    positions: List[Dict[str, Any]]
    cash: float
    net_liq: float


class IBKRClient:
    """Thin wrapper around :class:`ib_async.IB`.

    Provides ``connect``/``disconnect`` helpers with exponential backoff and a
    convenience ``snapshot`` method for retrieving account data.
    """

    def __init__(self, account_updates_timeout: float | None = None) -> None:
        self._ib = IB()
        # Connection parameters used by the async context manager methods.
        self._host: str | None = None
        self._port: int | None = None
        self._client_id: int | None = None
        # Timeout for reqAccountUpdatesAsync calls in snapshot.
        self._account_updates_timeout = (
            account_updates_timeout if account_updates_timeout is not None else 10.0
        )

    async def __aenter__(self) -> "IBKRClient":
        """Connect to IBKR using stored connection parameters."""
        if self._host is None or self._port is None or self._client_id is None:
            raise IBKRError("Connection parameters not set")
        await self.connect(self._host, self._port, self._client_id)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Disconnect from IBKR on context manager exit."""
        if self._host is None or self._port is None or self._client_id is None:
            return
        await self.disconnect(self._host, self._port, self._client_id)

    async def connect(self, host: str, port: int, client_id: int) -> None:
        """Connect to TWS/Gateway with exponential backoff."""

        await retry_async(
            lambda: self._ib.connectAsync(host, port, clientId=client_id),
            retries=3,
            base_delay=0.5,
            action="connect to IBKR",
        )
        log.info("Connected to IBKR")

    async def disconnect(self, host: str, port: int, client_id: int) -> None:
        """Disconnect from TWS/Gateway with exponential backoff."""

        await retry_async(
            self._ib.disconnect,
            retries=3,
            base_delay=0.5,
            action="disconnect from IBKR",
        )
        log.info("Disconnected from IBKR")

    async def snapshot(
        self,
        account_id: str,
        progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> Dict[str, Any]:
        """Return a snapshot of positions and account balances.

        The snapshot contains positions denominated in USD, the available cash
        in USD and the net liquidation value in USD with any CAD cash deducted
        after converting it to USD using the current FX rate.
        """

        try:
            log.info("Starting account snapshot for %s", account_id)

            # Retrieve raw positions for the account
            if progress is not None:
                await progress("requesting positions")
            positions: List[Position] = await self._ib.reqPositionsAsync()
            if progress is not None:
                await progress("received positions")
            positions = [p for p in positions if p.account == account_id]

            # Request portfolio updates which include market prices/values
            if progress is not None:
                await progress("requesting account updates")
            portfolio_items: List[Any] = []
            try:
                await asyncio.wait_for(
                    self._ib.reqAccountUpdatesAsync(account_id),
                    timeout=self._account_updates_timeout,
                )
                if progress is not None:
                    await progress("received account updates")
                portfolio_items = self._ib.portfolio()
            except asyncio.TimeoutError as exc:
                raise IBKRError(
                    f"account update request for {account_id} timed out"
                ) from exc
            finally:
                self._ib.client.reqAccountUpdates(False, account_id)
            portfolio_map = {
                (item.account, getattr(item.contract, "symbol", "")): item
                for item in portfolio_items
            }

            usd_positions: List[Dict[str, Any]] = []
            for p in positions:
                if p.contract.currency != "USD":
                    continue

                symbol = getattr(p.contract, "symbol", "")
                if progress is not None:
                    await progress(f"processing {symbol}")

                key = (p.account, symbol)
                item = portfolio_map.get(key)

                pos: Dict[str, Any] = {
                    "account": p.account,
                    "symbol": getattr(p.contract, "symbol", ""),
                    "position": p.position,
                    "avg_cost": p.avgCost,
                }
                if item is not None:
                    pos["market_price"] = item.marketPrice
                    pos["market_value"] = item.marketValue

                usd_positions.append(pos)

            # Ensure account summary data is fetched for the target account.
            # ``ib_async`` changed the signature of ``reqAccountSummaryAsync`` at
            # some point, so we try calling it with the account id first and
            # fall back to calling it without arguments if a ``TypeError`` is
            # raised.  Using ``cast`` avoids a mypy complaint about the
            # potentially varying call signature.
            if progress is not None:
                await progress("requesting account summary")
            req_summary = cast(Any, self._ib.reqAccountSummaryAsync)
            try:
                await req_summary(account_id)
            except TypeError:
                await req_summary()
            if progress is not None:
                await progress("received account summary")
            summary = await self._ib.accountSummaryAsync(account_id)
            summary = [
                s for s in summary if getattr(s, "account", account_id) == account_id
            ]

            cash_usd = 0.0
            net_liq_usd = 0.0
            cad_cash = 0.0
            cad_to_usd = 1.0

            for value in summary:
                if value.tag in {"CashBalance", "TotalCashValue"}:
                    if value.currency == "USD":
                        cash_usd = float(value.value)
                    elif value.currency == "CAD":
                        cad_cash = float(value.value)
                elif value.tag == "ExchangeRate" and value.currency == "CAD":
                    cad_to_usd = float(value.value)
                elif value.tag == "NetLiquidation" and value.currency == "USD":
                    net_liq_usd = float(value.value)

            net_liq_usd -= cad_cash * cad_to_usd

            snapshot = Snapshot(
                positions=usd_positions, cash=cash_usd, net_liq=net_liq_usd
            )
            log.info(
                "Snapshot complete: %d USD positions, cash %.2f, net_liq %.2f",
                len(usd_positions),
                cash_usd,
                net_liq_usd,
            )
            return asdict(snapshot)

        except IBKRError:
            raise
        except Exception as exc:  # pragma: no cover - snapshot errors
            log.exception("Snapshot for %s failed", account_id)
            raise IBKRError(f"snapshot for {account_id} failed: {exc}") from exc
