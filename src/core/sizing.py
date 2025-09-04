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

import logging
import math
from dataclasses import dataclass
from typing import Any, Mapping

from .drift import Drift


@dataclass
class SizedTrade:
    """Concrete sized trade for a symbol."""

    symbol: str
    action: str  # ``"BUY"`` or ``"SELL"``
    quantity: float
    notional: float


def _extract_cfg(cfg: Any) -> tuple[int, bool, str, float | None, float | None, float]:
    """Return relevant rebalance configuration values."""

    try:
        reb = cfg.rebalance  # type: ignore[attr-defined]
        return (
            reb.min_order_usd,
            reb.allow_fractional,
            reb.cash_buffer_type.lower(),
            getattr(reb, "cash_buffer_pct", None),
            getattr(reb, "cash_buffer_abs", None),
            reb.max_leverage,
        )
    except AttributeError as exc:  # pragma: no cover - defensive
        raise AttributeError("cfg.rebalance is missing required fields") from exc


def size_orders(
    account_id: str,
    drifts: list[Drift],
    prices: Mapping[str, float],
    cash: float,
    net_liq: float,
    cfg: Any,
) -> tuple[list[SizedTrade], float, float]:
    """Size trades based on drift information.

    Parameters
    ----------
    account_id:
        Account identifier used for logging context.
    drifts:
        Prioritised drift records.
    prices:
        Mapping of symbols to current prices.
    cash:
        Current cash balance in USD.
    net_liq:
        Net liquidation value used for leverage calculations.
    cfg:
        Configuration object containing ``rebalance`` settings.

    Returns
    -------
    tuple[list[SizedTrade], float, float]
        A list of :class:`SizedTrade` objects along with the projected gross
        exposure and leverage after applying the trades.
    """

    logging.debug("Sizing orders for account %s", account_id)

    (
        min_order_usd,
        allow_fractional,
        cash_buffer_type,
        cash_buffer_pct,
        cash_buffer_abs,
        max_leverage,
    ) = _extract_cfg(cfg)

    if cash_buffer_type == "pct":
        reserve = net_liq * (cash_buffer_pct or 0.0)
    else:
        reserve = cash_buffer_abs or 0.0
    available = cash - reserve

    trades: list[SizedTrade] = []
    total_buy = 0.0
    total_sell = 0.0
    unmet_buys: list[tuple[str, float]] = []

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
            # Greedy spend limited by current availability.
            spend_cap = min(notional, max(0.0, available))
            qty = spend_cap / price if spend_cap > 0 else 0.0
            if not math.isfinite(qty):
                raise ValueError(f"non-finite quantity for {d.symbol}: {qty}")
            if not allow_fractional:
                qty = float(int(qty))
                spend_cap = qty * price
            if spend_cap < min_order_usd or qty == 0:
                unmet_buys.append((d.symbol, notional))
                continue
            trades.append(SizedTrade(d.symbol, "BUY", qty, spend_cap))
            available -= spend_cap
            total_buy += spend_cap
            if spend_cap < notional:
                unmet_buys.append((d.symbol, notional - spend_cap))
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

    # If later sells freed cash, allocate it across previously unmet buys
    # proportionally to their missing notional.
    if available > 0 and unmet_buys:
        total_unmet = sum(miss for _sym, miss in unmet_buys)
        allocatable = min(available, total_unmet)
        additional: list[SizedTrade] = []
        for symbol, miss in unmet_buys:
            portion = allocatable * (miss / total_unmet)
            if portion <= 0:
                continue
            price = prices[symbol]
            if not math.isfinite(price):
                raise ValueError(f"non-finite price for {symbol}: {price}")
            qty = portion / price
            if not math.isfinite(qty):
                raise ValueError(f"non-finite quantity for {symbol}: {qty}")
            if not allow_fractional:
                qty = float(int(qty))
                portion = qty * price
            if portion < min_order_usd or qty == 0:
                continue
            additional.append(SizedTrade(symbol, "BUY", qty, portion))

        if additional:
            added_notional = sum(t.notional for t in additional)
            available -= added_notional
            total_buy += added_notional
            trades.extend(additional)

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
