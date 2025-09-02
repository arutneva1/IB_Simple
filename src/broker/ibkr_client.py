"""Client abstraction for ``ib_async``.

This module provides a small wrapper around :class:`ib_async.IB` with a
convenience ``connect``/``disconnect`` API that retries once before raising a
custom :class:`IBKRError`.  A ``snapshot`` method is also provided to fetch the
current account state in a simplified dictionary form.
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any, Dict, List

from ib_async import IB, Position


class IBKRError(Exception):
    """Custom exception raised when IBKR operations fail."""


@dataclass
class Snapshot:
    """Lightweight container for account snapshot data."""

    positions: List[Dict[str, Any]]
    cash: float
    net_liq: float


class IBKRClient:
    """Thin wrapper around :class:`ib_async.IB`."""

    def __init__(self) -> None:
        self._ib = IB()

    async def connect(self, host: str, port: int, client_id: int) -> None:
        """Connect to TWS/Gateway.

        Retries once after a short delay and raises :class:`IBKRError` when the
        connection cannot be established.
        """

        for attempt in range(2):
            try:
                await self._ib.connectAsync(host, port, clientId=client_id)
                return
            except Exception as exc:  # pragma: no cover - ib connection errors
                if attempt:
                    raise IBKRError("Failed to connect to IBKR") from exc
                await asyncio.sleep(0.5)

    async def disconnect(self, host: str, port: int, client_id: int) -> None:
        """Disconnect from TWS/Gateway.

        The *host*, *port* and *client_id* arguments are accepted for a symmetric
        API with :meth:`connect` but are not used.  The method retries once
        before raising :class:`IBKRError`.
        """

        for attempt in range(2):
            try:
                self._ib.disconnect()
                return
            except Exception as exc:  # pragma: no cover - ib disconnection errors
                if attempt:
                    raise IBKRError("Failed to disconnect from IBKR") from exc
                await asyncio.sleep(0.5)

    async def snapshot(self, account_id: str) -> Dict[str, Any]:
        """Return a snapshot of positions and account balances.

        The snapshot contains positions denominated in USD, the available cash
        in USD and the net liquidation value in USD with any CAD cash deducted.
        """

        try:
            positions: List[Position] = await self._ib.reqPositionsAsync()
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

            # Ensure account summary data is fetched
            await self._ib.reqAccountSummaryAsync()
            summary = await self._ib.accountSummaryAsync(account_id)

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
            return asdict(snapshot)

        except Exception as exc:  # pragma: no cover - snapshot errors
            raise IBKRError("Failed to create account snapshot") from exc
