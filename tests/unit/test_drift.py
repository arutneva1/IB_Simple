"""Tests for :mod:`core.drift` compute_drift function."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.drift import compute_drift


def test_compute_drift_normalizes_and_combines_targets() -> None:
    """Drift uses prices and net liquidation to compute weight percentages."""

    current = {"AAA": 10, "CASH": 5000}
    targets = {"AAA": 50.0, "BBB": 50.0, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 100.0}
    net_liq = 6000.0  # 10*100 + 5000

    drifts = compute_drift(current, targets, prices, net_liq, cfg=None)
    by_symbol = {d.symbol: d for d in drifts}

    assert len(drifts) == 3

    aaa = by_symbol["AAA"]
    assert aaa.target_wt_pct == pytest.approx(50.0)
    assert aaa.current_wt_pct == pytest.approx(16.6667, rel=1e-4)
    assert aaa.drift_pct == pytest.approx(-33.3333, rel=1e-4)
    assert aaa.drift_usd == pytest.approx(-2000.0)
    assert aaa.action == "BUY"

    bbb = by_symbol["BBB"]
    assert bbb.current_wt_pct == pytest.approx(0.0)
    assert bbb.target_wt_pct == pytest.approx(50.0)
    assert bbb.drift_pct == pytest.approx(-50.0)
    assert bbb.drift_usd == pytest.approx(-3000.0)
    assert bbb.action == "BUY"

    cash = by_symbol["CASH"]
    assert cash.current_wt_pct == pytest.approx(83.3333, rel=1e-4)
    assert cash.target_wt_pct == pytest.approx(0.0)
    assert cash.drift_pct == pytest.approx(83.3333, rel=1e-4)
    assert cash.drift_usd == pytest.approx(5000.0)
    assert cash.action == "SELL"


def test_compute_drift_defaults_missing_targets_to_zero() -> None:
    """Symbols absent from targets are treated as having 0% target weight."""

    current = {"AAA": 5, "CCC": 10, "CASH": 0}
    targets = {"AAA": 60.0, "BBB": 40.0}
    prices = {"AAA": 100.0, "CCC": 10.0, "BBB": 100.0}
    net_liq = 600.0  # 5*100 + 10*10

    drifts = compute_drift(current, targets, prices, net_liq, cfg=None)
    by_symbol = {d.symbol: d for d in drifts}

    # Ensure "CCC" (missing from targets) defaults to 0 target weight
    ccc = by_symbol["CCC"]
    assert ccc.target_wt_pct == pytest.approx(0.0)
    assert ccc.current_wt_pct == pytest.approx(16.6667, rel=1e-4)
    assert ccc.drift_pct == pytest.approx(16.6667, rel=1e-4)
    assert ccc.drift_usd == pytest.approx(100.0)
    assert ccc.action == "SELL"

    # "BBB" (missing from current) is treated as 0 current weight
    bbb = by_symbol["BBB"]
    assert bbb.current_wt_pct == pytest.approx(0.0)
    assert bbb.target_wt_pct == pytest.approx(40.0)
    assert bbb.drift_pct == pytest.approx(-40.0)
    assert bbb.drift_usd == pytest.approx(-240.0)
    assert bbb.action == "BUY"
