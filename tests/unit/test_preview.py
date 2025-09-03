"""Tests for the preview renderer."""

from __future__ import annotations

from types import SimpleNamespace

from src.core.drift import Drift, prioritize_by_drift
from src.core.preview import render
from src.core.sizing import SizedTrade, size_orders


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
    table = render(prioritized, [], 0.0, 0.0)

    assert "Drift %" in table
    assert "BBB" not in table
    assert table.index("CCC") < table.index("AAA")


def test_render_shows_quantities_and_notional() -> None:
    drifts = [Drift("AAA", 0.0, 0.0, 0.0, -100.0, "BUY")]
    prices = {"AAA": 25.0}
    cfg = _cfg(1)

    prioritized = prioritize_by_drift(drifts, cfg)
    trades, *_ = size_orders(prioritized, prices, cash=100.0, cfg=cfg)
    table = render(prioritized, trades, 100.0, 1.0)

    assert "Qty" in table
    assert "Notional" in table
    assert "4.00" in table
    assert "100.00" in table


def test_render_batch_summary() -> None:
    drifts = [
        Drift("AAA", 0.0, 0.0, 0.0, -100.0, "BUY"),
        Drift("BBB", 0.0, 0.0, 0.0, 50.0, "SELL"),
    ]
    trades = [
        SizedTrade("AAA", "BUY", 10.0, 100.0),
        SizedTrade("BBB", "SELL", 10.0, 50.0),
    ]

    table = render(drifts, trades, pre_gross_exposure=500.0, pre_leverage=1.0)

    header = table.splitlines()[1]
    assert (
        header
        == "┃ Symbol ┃ Target % ┃ Current % ┃ Drift % ┃ Drift $ ┃ Action ┃   Qty ┃ Notional ┃"
    )

    assert "Batch Summary" in table
    for line in [
        "│ Gross Buy           │ 100.00 │",
        "│ Gross Sell          │  50.00 │",
        "│ Pre Gross Exposure  │ 500.00 │",
        "│ Pre Leverage        │   1.00 │",
        "│ Post Gross Exposure │ 550.00 │",
        "│ Post Leverage       │   1.10 │",
    ]:
        assert line in table
