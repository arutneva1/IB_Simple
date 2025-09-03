"""Tests for trade sizing logic."""

from __future__ import annotations

from types import SimpleNamespace

from src.core import Drift, SizedTrade, size_orders


def _cfg(
    *,
    min_order_usd: int = 1,
    allow_fractional: bool = False,
    cash_buffer_pct: float = 0.0,
    max_leverage: float = 1.0,
):
    reb = SimpleNamespace(
        min_order_usd=min_order_usd,
        allow_fractional=allow_fractional,
        cash_buffer_pct=cash_buffer_pct,
        max_leverage=max_leverage,
    )
    return SimpleNamespace(rebalance=reb)


def _drift(symbol: str, usd: float, net_liq: float) -> Drift:
    pct = usd / net_liq * 100.0
    action = "BUY" if usd < 0 else "SELL" if usd > 0 else "HOLD"
    # The specific target/current weights are irrelevant for sizing; they only
    # need to differ by ``pct``.
    current = 0.0
    target = -pct
    return Drift(symbol, target, current, pct, usd, action)


def test_sizes_buy_respecting_cash_buffer_and_rounding() -> None:
    net_liq = 1000.0
    drifts = [_drift("AAA", -150.0, net_liq)]
    prices = {"AAA": 10.0}
    cfg = _cfg(cash_buffer_pct=0.1)  # reserve 100 USD

    trades, gross, lev = size_orders(drifts, prices, cash=200.0, cfg=cfg)

    assert trades == [SizedTrade("AAA", "BUY", 10.0, 100.0)]
    assert gross == 900.0
    assert lev == 0.9


def test_drops_orders_below_min_after_rounding() -> None:
    net_liq = 1000.0
    drifts = [_drift("AAA", -80.0, net_liq)]
    prices = {"AAA": 45.0}
    cfg = _cfg(min_order_usd=50)

    trades, gross, lev = size_orders(drifts, prices, cash=600.0, cfg=cfg)

    assert trades == []
    assert gross == 400.0  # exposure unchanged
    assert lev == 0.4


def test_scales_down_low_priority_buys_to_meet_leverage() -> None:
    net_liq = 1000.0
    drifts = [_drift("AAA", -100.0, net_liq), _drift("BBB", -100.0, net_liq)]
    prices = {"AAA": 10.0, "BBB": 10.0}
    cfg = _cfg(max_leverage=0.85)

    trades, gross, lev = size_orders(drifts, prices, cash=200.0, cfg=cfg)

    assert trades == [SizedTrade("AAA", "BUY", 5.0, 50.0)]
    assert gross == 850.0
    assert lev == 0.85

