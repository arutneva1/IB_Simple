"""Portfolio drift calculations.

This module compares the current portfolio allocation against target weights
and reports the difference both in percent and dollar terms.  The resulting
records drive later sizing and execution logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

from src.io import ConfigError


@dataclass(frozen=True)
class Drift:
    """Represents drift for a single symbol.

    Attributes
    ----------
    symbol:
        Ticker symbol or ``"CASH"`` for cash balances.
    target_wt_pct:
        Desired portfolio weight in percent.
    current_wt_pct:
        Current portfolio weight in percent.
    drift_pct:
        Difference between current and target weights (``current-target``).
    drift_usd:
        Dollar value of the drift.  Positive values indicate an overweight
        position (requiring a sell to rebalance) while negative values indicate
        an underweight position (requiring a buy).
    action:
        Suggested action: ``"BUY"`` when underweight, ``"SELL"`` when
        overweight and ``"HOLD"`` when within the target.
    """

    symbol: str
    target_wt_pct: float
    current_wt_pct: float
    drift_pct: float
    drift_usd: float
    action: str


def compute_drift(
    account_id: str,
    current: Mapping[str, float],
    targets: Mapping[str, float],
    prices: Mapping[str, float],
    net_liq: float,
    cfg: Any,
) -> list[Drift]:
    """Compute portfolio drift records.

    The ``net_liq`` value is reduced by any configured cash buffer in
    ``cfg.rebalance``.  The resulting investable net liquidation value is
    floored at zero to avoid negative weights; if the buffer exceeds the
    available ``net_liq`` a :class:`ConfigError` is raised.

    Parameters
    ----------
    account_id:
        Account identifier used for logging context.
    current:
        Mapping of symbols to share quantities.  ``"CASH"`` represents the
        dollar value of cash holdings.
    targets:
        Target weights in percent for each symbol.
    prices:
        Mapping of symbols to current market prices.  ``"CASH"`` is implicitly
        priced at ``1``.
    net_liq:
        Net liquidation value of the portfolio in USD.
    cfg:
        Configuration object with optional ``rebalance`` settings, including
        ``cash_buffer_type`` and ``cash_buffer_pct``/``cash_buffer_abs``.

    Returns
    -------
    list[Drift]
        One :class:`Drift` record per symbol present in either ``current`` or
        ``targets``.  The list is sorted alphabetically by symbol to ensure
        deterministic output.
    """

    logging.debug("Computing drift for account %s", account_id)

    # Determine current weights for all held symbols.
    values: dict[str, float] = {}
    for symbol, qty in current.items():
        if symbol == "CASH":
            value = qty
        else:
            try:
                price = prices[symbol]
            except KeyError as exc:  # pragma: no cover - defensive programming
                raise KeyError(f"missing price for {symbol}") from exc
            value = qty * price
        values[symbol] = value

    investable_net_liq = net_liq
    if cfg is not None:
        try:
            reb = cfg.rebalance  # type: ignore[attr-defined]
        except AttributeError:
            pass
        else:
            buffer_type = getattr(reb, "cash_buffer_type", "pct").lower()
            if buffer_type == "pct":
                buffer = net_liq * getattr(reb, "cash_buffer_pct", 0.0)
            elif buffer_type == "abs":
                buffer = getattr(reb, "cash_buffer_abs", 0.0)
            else:
                buffer = 0.0
            if buffer > net_liq:
                raise ConfigError("cash buffer exceeds available net liquidity")
            investable_net_liq -= buffer

    investable_net_liq = max(investable_net_liq, 0.0)

    current_wts = {
        sym: (val / investable_net_liq * 100.0 if investable_net_liq else 0.0)
        for sym, val in values.items()
    }

    # Union of all symbols from current holdings and targets.
    symbols = set(current_wts) | set(targets)

    drifts: list[Drift] = []
    for symbol in sorted(symbols):
        target = targets.get(symbol, 0.0)
        current_wt = current_wts.get(symbol, 0.0)
        drift_pct = current_wt - target
        drift_usd = investable_net_liq * drift_pct / 100.0

        if drift_pct > 0:
            action = "SELL"
        elif drift_pct < 0:
            action = "BUY"
        else:
            action = "HOLD"

        drifts.append(
            Drift(
                symbol=symbol,
                target_wt_pct=target,
                current_wt_pct=current_wt,
                drift_pct=drift_pct,
                drift_usd=drift_usd,
                action=action,
            )
        )

    if cfg is not None:
        try:
            rebalance_cfg = cfg.rebalance  # type: ignore[attr-defined]
            trigger_mode = rebalance_cfg.trigger_mode
        except AttributeError:  # pragma: no cover - defensive
            pass
        else:
            if trigger_mode == "per_holding":
                band = rebalance_cfg.per_holding_band_bps / 10_000.0
                drifts = [d for d in drifts if abs(d.drift_pct) / 100.0 > band]
            elif trigger_mode == "total_drift":
                total_band = rebalance_cfg.portfolio_total_band_bps / 10_000.0
                total_drift = sum(abs(d.drift_pct) / 100.0 for d in drifts)
                if total_drift > total_band:
                    ranked = sorted(
                        drifts, key=lambda d: abs(d.drift_pct), reverse=True
                    )
                    selected: list[Drift] = []
                    remaining = total_drift
                    for d in ranked:
                        selected.append(d)
                        remaining -= abs(d.drift_pct) / 100.0
                        if remaining <= total_band:
                            break
                    drifts = sorted(selected, key=lambda d: d.symbol)
                else:
                    drifts = []

    return drifts


def prioritize_by_drift(account_id: str, drifts: list[Drift], cfg: Any) -> list[Drift]:
    """Filter and sort drifts by dollar magnitude.

    Parameters
    ----------
    account_id:
        Account identifier used for logging context.
    drifts:
        Drift records to evaluate.
    cfg:
        Configuration with ``rebalance.min_order_usd``.

    Returns
    -------
    list[Drift]
        Drifts whose absolute dollar value exceeds ``min_order_usd``,
        sorted from largest to smallest by absolute drift.
    """

    logging.debug("Prioritizing drifts for account %s", account_id)

    try:
        min_order = cfg.rebalance.min_order_usd  # type: ignore[attr-defined]
    except AttributeError as exc:  # pragma: no cover - defensive
        raise AttributeError("cfg.rebalance.min_order_usd is required") from exc

    filtered = [d for d in drifts if abs(d.drift_usd) >= min_order]
    return sorted(filtered, key=lambda d: abs(d.drift_usd), reverse=True)


__all__ = ["Drift", "compute_drift", "prioritize_by_drift"]
