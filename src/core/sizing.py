"""Trade sizing logic.

This module converts :class:`~src.core.drift.Drift` records into concrete trade
sizes while enforcing cash buffers and leverage limits.  The algorithm works in
two phases:

* Greedily allocate capital to the highest priority drifts while respecting the
  available cash after reserving a configurable buffer.
* Compute the projected portfolio exposure and scale back the lowest priority
  buy orders until the requested leverage does not exceed ``max_leverage``.

It returns the final list of sized trades along with exposure information that
can be used for preview purposes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .drift import Drift


@dataclass
class SizedTrade:
    """Concrete sized trade for a symbol."""

    symbol: str
    action: str  # ``"BUY"`` or ``"SELL"``
    quantity: float
    notional: float


def _extract_cfg(cfg: Any) -> tuple[int, bool, float, float]:
    """Return relevant rebalance configuration values.

    ``cash_buffer_pct`` is expected as a decimal fraction (e.g., ``0.01`` for 1%).
    """

    try:
        reb = cfg.rebalance  # type: ignore[attr-defined]
        return (
            reb.min_order_usd,
            reb.allow_fractional,
            reb.cash_buffer_pct,
            reb.max_leverage,
        )
    except AttributeError as exc:  # pragma: no cover - defensive
        raise AttributeError("cfg.rebalance is missing required fields") from exc


def _infer_net_liq(drifts: Iterable[Drift], cash: float) -> float:
    """Infer ``net_liq`` from the provided drifts.

    ``compute_drift`` derives all ``drift_usd`` values from a common net
    liquidation figure.  We reverse that relationship here by taking the first
    non-zero drift percentage.  When no such drift is available we fall back to
    the cash balance which is a reasonable approximation for an empty
    portfolio.
    """

    for d in drifts:
        if d.drift_pct != 0:
            return d.drift_usd * 100.0 / d.drift_pct
    return cash


def size_orders(
    drifts: list[Drift],
    prices: Mapping[str, float],
    cash: float,
    cfg: Any,
) -> tuple[list[SizedTrade], float, float]:
    """Size trades based on drift information.

    Parameters
    ----------
    drifts:
        Prioritised drift records.
    prices:
        Mapping of symbols to current prices.
    cash:
        Current cash balance in USD.
    cfg:
        Configuration object containing ``rebalance`` settings.

    Returns
    -------
    tuple[list[SizedTrade], float, float]
        A list of :class:`SizedTrade` objects along with the projected gross
        exposure and leverage after applying the trades.
    """

    min_order_usd, allow_fractional, cash_buffer_pct, max_leverage = _extract_cfg(cfg)

    net_liq = _infer_net_liq(drifts, cash)

    reserve = net_liq * cash_buffer_pct  # cfg.cash_buffer_pct is already a decimal
    available = cash - reserve

    trades: list[SizedTrade] = []
    total_buy = 0.0
    total_sell = 0.0

    for d in drifts:
        if d.symbol == "CASH":
            continue
        try:
            price = prices[d.symbol]
        except KeyError as exc:  # pragma: no cover - defensive
            raise KeyError(f"missing price for {d.symbol}") from exc
        if not math.isfinite(price):
            raise ValueError(f"non-finite price for {d.symbol}: {price}")

        notional = abs(d.drift_usd)
        if d.action == "BUY":
            spend = min(notional, max(0.0, available))
            if spend <= 0:
                continue
            qty = spend / price
            if not math.isfinite(qty):
                raise ValueError(f"non-finite quantity for {d.symbol}: {qty}")
            if not allow_fractional:
                qty = float(int(qty))
                spend = qty * price
            if spend < min_order_usd:
                continue
            trades.append(SizedTrade(d.symbol, "BUY", qty, spend))
            available -= spend
            total_buy += spend
        elif d.action == "SELL":
            qty = notional / price
            if not math.isfinite(qty):
                raise ValueError(f"non-finite quantity for {d.symbol}: {qty}")
            if not allow_fractional:
                qty = float(int(qty))
                notional = qty * price
            if notional < min_order_usd:
                continue
            trades.append(SizedTrade(d.symbol, "SELL", qty, notional))
            available += notional
            total_sell += notional

    gross_exposure = (net_liq - cash) + total_buy - total_sell
    leverage = gross_exposure / net_liq if net_liq else 0.0

    if leverage > max_leverage and total_buy > 0:
        excess = gross_exposure - max_leverage * net_liq
        for trade in reversed(trades):
            if trade.action != "BUY":
                continue
            if excess <= 0:
                break

            reduction = min(trade.notional, excess)
            new_notional = trade.notional - reduction
            price = prices[trade.symbol]
            if not math.isfinite(price):
                raise ValueError(f"non-finite price for {trade.symbol}: {price}")
            qty = new_notional / price
            if not math.isfinite(qty):
                raise ValueError(f"non-finite quantity for {trade.symbol}: {qty}")
            if not allow_fractional:
                qty = float(int(qty))
                new_notional = qty * price

            if new_notional < min_order_usd or qty == 0:
                excess -= trade.notional
                total_buy -= trade.notional
                trades.remove(trade)
            else:
                excess -= trade.notional - new_notional
                total_buy -= trade.notional - new_notional
                trade.quantity = qty
                trade.notional = new_notional

        gross_exposure = (net_liq - cash) + total_buy - total_sell
        leverage = gross_exposure / net_liq if net_liq else 0.0
    # Collapse any duplicated trades by symbol, netting opposing actions.
    aggregated_qty: dict[str, float] = {}
    aggregated_notional: dict[str, float] = {}
    for t in trades:
        sign = 1.0 if t.action == "BUY" else -1.0
        aggregated_qty[t.symbol] = aggregated_qty.get(t.symbol, 0.0) + sign * t.quantity
        aggregated_notional[t.symbol] = (
            aggregated_notional.get(t.symbol, 0.0) + sign * t.notional
        )

    normalized: list[SizedTrade] = []
    for symbol, qty in aggregated_qty.items():
        notional = aggregated_notional[symbol]
        if qty > 0 and notional > 0:
            normalized.append(SizedTrade(symbol, "BUY", qty, notional))
        elif qty < 0 and notional < 0:
            normalized.append(SizedTrade(symbol, "SELL", -qty, -notional))
        # else qty and notional cancel out -> no trade

    return normalized, gross_exposure, leverage


__all__ = ["SizedTrade", "size_orders"]
