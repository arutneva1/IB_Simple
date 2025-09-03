"""Tests for the preview renderer."""

from __future__ import annotations

from types import SimpleNamespace

from src.core.drift import Drift, prioritize_by_drift
from src.core.preview import render
from src.core.sizing import size_orders


def _cfg(
    min_usd: int,
    allow_fractional: bool = True,
    cash_buffer_pct: float = 0.0,
    max_leverage: float = 1.0,
) -> SimpleNamespace:
    reb = SimpleNamespace(
        min_order_usd=min_usd,
        allow_fractional=allow_fractional,
        cash_buffer_pct=cash_buffer_pct,
        max_leverage=max_leverage,
    )
    return SimpleNamespace(rebalance=reb)


def test_render_sorted_and_filtered() -> None:
    drifts = [
        Drift("AAA", 0.0, 0.0, 0.0, -120.0, "BUY"),
        Drift("BBB", 0.0, 0.0, 0.0, 80.0, "SELL"),
        Drift("CCC", 0.0, 0.0, 0.0, 200.0, "SELL"),
    ]
    cfg = _cfg(100)

    prioritized = prioritize_by_drift(drifts, cfg)
    table = render(prioritized)

    assert "BBB" not in table
    assert table.index("CCC") < table.index("AAA")


def test_render_shows_quantities() -> None:
    drifts = [Drift("AAA", 0.0, 0.0, 0.0, -100.0, "BUY")]
    prices = {"AAA": 25.0}
    cfg = _cfg(1)

    prioritized = prioritize_by_drift(drifts, cfg)
    trades, *_ = size_orders(prioritized, prices, cash=100.0, cfg=cfg)
    table = render(prioritized, trades)

    assert "Qty" in table
    assert "4.00" in table
