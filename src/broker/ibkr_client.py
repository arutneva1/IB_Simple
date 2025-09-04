"""Client abstraction for ``ib_async``.

This module provides a small wrapper around :class:`ib_async.IB` with
exponential-backoff ``connect``/``disconnect`` helpers that raise
``IBKRError`` after repeated failures.  A ``snapshot`` method is also provided
to fetch the current account state in a simplified dictionary form.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, cast

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
    """Thin wrapper around :class:`ib_async.IB` with context manager support."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        client_id: int | None = None,
    ) -> None:
        self._ib = IB()
        self._host = host
        self._port = port
        self._client_id = client_id

    async def __aenter__(self) -> "IBKRClient":
        """Connect to IBKR when used as an async context manager."""

        if None in (self._host, self._port, self._client_id):
            raise IBKRError("host, port and client_id required for context manager")
        assert (
            self._host is not None
            and self._port is not None
            and self._client_id is not None
        )
        await self.connect(self._host, self._port, self._client_id)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        """Ensure disconnection even if an error occurred in the context."""

        if None not in (self._host, self._port, self._client_id):
            try:
                assert (
                    self._host is not None
                    and self._port is not None
                    and self._client_id is not None
                )
                await self.disconnect(self._host, self._port, self._client_id)
            except Exception:  # pragma: no cover - disconnect errors
                log.exception("Error while disconnecting from IBKR")
                if exc_type is None:
                    raise
        return False

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

    async def snapshot(self, account_id: str) -> Dict[str, Any]:
        """Return a snapshot of positions and account balances.

        The snapshot contains positions denominated in USD, the available cash
        in USD and the net liquidation value in USD with any CAD cash deducted.
        """

        try:
            log.info("Starting account snapshot for %s", account_id)
            positions: List[Position] = await self._ib.reqPositionsAsync()
            positions = [p for p in positions if p.account == account_id]
            usd_positions = [
                {
                    "account": p.account,
                    "symbol": getattr(p.contract, "symbol", ""),
                    "position": p.position,
                    "avg_cost": p.avgCost,
                }
                for p in positions
                if p.contract.currency == "USD"
            ]

            # Ensure account summary data is fetched for the target account.
            # ``ib_async`` changed the signature of ``reqAccountSummaryAsync`` at
            # some point, so we try calling it with the account id first and
            # fall back to calling it without arguments if a ``TypeError`` is
            # raised.  Using ``cast`` avoids a mypy complaint about the
            # potentially varying call signature.
            req_summary = cast(Any, self._ib.reqAccountSummaryAsync)
            try:
                await req_summary(account_id)
            except TypeError:
                await req_summary()
            summary = await self._ib.accountSummaryAsync(account_id)
            summary = [
                s for s in summary if getattr(s, "account", account_id) == account_id
            ]

            cash_usd = 0.0
            net_liq_usd = 0.0
            cad_cash = 0.0

            for value in summary:
                if value.tag in {"CashBalance", "TotalCashValue"}:
                    if value.currency == "USD":
                        cash_usd = float(value.value)
                    elif value.currency == "CAD":
                        cad_cash = float(value.value)
                elif value.tag == "NetLiquidation" and value.currency == "USD":
                    net_liq_usd = float(value.value)

            net_liq_usd -= cad_cash

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

        except Exception as exc:  # pragma: no cover - snapshot errors
            log.exception("Snapshot for %s failed", account_id)
            raise IBKRError(f"snapshot for {account_id} failed: {exc}") from exc
