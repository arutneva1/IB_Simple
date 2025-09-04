"""Tests for drift prioritization."""

from __future__ import annotations

from types import SimpleNamespace

from src.core.drift import Drift, prioritize_by_drift


def _cfg(min_usd: int) -> SimpleNamespace:
    return SimpleNamespace(rebalance=SimpleNamespace(min_order_usd=min_usd))


def test_prioritize_filters_and_sorts_by_abs_drift_usd() -> None:
    drifts = [
        Drift("AAA", 0.0, 0.0, 0.0, -120.0, "BUY"),
        Drift("BBB", 0.0, 0.0, 0.0, 80.0, "SELL"),
        Drift("CCC", 0.0, 0.0, 0.0, 200.0, "SELL"),
    ]
    cfg = _cfg(100)

    prioritized = prioritize_by_drift("ACCT", drifts, cfg)

    assert [d.symbol for d in prioritized] == ["CCC", "AAA"]


def test_prioritize_retains_all_when_threshold_zero() -> None:
    drifts = [
        Drift("AAA", 0.0, 0.0, 0.0, -120.0, "BUY"),
        Drift("BBB", 0.0, 0.0, 0.0, 80.0, "SELL"),
    ]
    cfg = _cfg(0)

    prioritized = prioritize_by_drift("ACCT", drifts, cfg)

    assert [d.symbol for d in prioritized] == ["AAA", "BBB"]
