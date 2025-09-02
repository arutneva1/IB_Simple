"""Tests for the preview renderer."""

from __future__ import annotations

from types import SimpleNamespace

from src.core.drift import Drift, prioritize_by_drift
from src.core.preview import render


def _cfg(min_usd: int) -> SimpleNamespace:
    return SimpleNamespace(rebalance=SimpleNamespace(min_order_usd=min_usd))


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
