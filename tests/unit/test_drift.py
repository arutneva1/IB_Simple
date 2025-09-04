"""Tests for :mod:`core.drift` compute_drift function."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.drift import Drift, compute_drift, prioritize_by_drift


def test_compute_drift_normalizes_and_combines_targets() -> None:
    """Drift uses prices and net liquidation to compute weight percentages."""

    current = {"AAA": 10, "CASH": 5000}
    targets = {"AAA": 50.0, "BBB": 50.0, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 100.0}
    net_liq = 6000.0  # 10*100 + 5000

    drifts = compute_drift("ACCT", current, targets, prices, net_liq, cfg=None)
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


@pytest.mark.parametrize(
    "reb_cfg,investable_net_liq",
    [
        (
            SimpleNamespace(cash_buffer_type="pct", cash_buffer_pct=0.1),
            6000.0 * (1 - 0.1),
        ),
        (
            SimpleNamespace(cash_buffer_type="abs", cash_buffer_abs=600.0),
            6000.0 - 600.0,
        ),
    ],
)
def test_compute_drift_respects_cash_buffer(
    reb_cfg: SimpleNamespace, investable_net_liq: float
) -> None:
    """Cash buffer reduces investable NetLiq for drift calculations."""

    current = {"AAA": 10, "CASH": 5000}
    targets = {"AAA": 50.0, "BBB": 50.0, "CASH": 0.0}
    prices = {"AAA": 100.0, "BBB": 100.0}
    net_liq = 6000.0
    cfg = SimpleNamespace(rebalance=reb_cfg)

    drifts = compute_drift("ACCT", current, targets, prices, net_liq, cfg)
    by_symbol = {d.symbol: d for d in drifts}

    aaa = by_symbol["AAA"]
    assert aaa.current_wt_pct == pytest.approx(
        1000 / investable_net_liq * 100, rel=1e-4
    )
    assert aaa.drift_pct == pytest.approx(-31.4815, rel=1e-4)
    assert aaa.drift_usd == pytest.approx(-1700.0, rel=1e-4)
    assert aaa.action == "BUY"

    bbb = by_symbol["BBB"]
    assert bbb.drift_usd == pytest.approx(-2700.0, rel=1e-4)

    cash = by_symbol["CASH"]
    assert cash.drift_usd == pytest.approx(5000.0)


def test_compute_drift_defaults_missing_targets_to_zero() -> None:
    """Symbols absent from targets are treated as having 0% target weight."""

    current = {"AAA": 5, "CCC": 10, "CASH": 0}
    targets = {"AAA": 60.0, "BBB": 40.0}
    prices = {"AAA": 100.0, "CCC": 10.0, "BBB": 100.0}
    net_liq = 600.0  # 5*100 + 10*10

    drifts = compute_drift("ACCT", current, targets, prices, net_liq, cfg=None)
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


@pytest.fixture
def sample_prices() -> dict[str, float]:
    return {"AAA": 1.0, "BBB": 1.0, "CCC": 1.0, "DDD": 1.0}


@pytest.fixture
def per_holding_current() -> dict[str, int]:
    return {"AAA": 45, "BBB": 36, "CCC": 19, "DDD": 0}


@pytest.fixture
def per_holding_targets() -> dict[str, float]:
    return {"AAA": 40.0, "BBB": 40.0, "CCC": 20.0, "DDD": 0.0}


@pytest.fixture
def total_current() -> dict[str, int]:
    return {"AAA": 46, "BBB": 25, "CCC": 29}


@pytest.fixture
def total_targets() -> dict[str, float]:
    return {"AAA": 40.0, "BBB": 30.0, "CCC": 30.0}


@pytest.fixture
def cfg_factory():
    def _make_cfg(
        trigger_mode: str = "",
        per_band: int = 0,
        total_band: int = 0,
        min_order: int = 0,
    ) -> SimpleNamespace:
        rebalance = SimpleNamespace(
            trigger_mode=trigger_mode,
            per_holding_band_bps=per_band,
            portfolio_total_band_bps=total_band,
            min_order_usd=min_order,
        )
        return SimpleNamespace(rebalance=rebalance)

    return _make_cfg


def test_per_holding_mode_triggers_symbols_and_skips_small_drifts(
    per_holding_current,
    per_holding_targets,
    sample_prices,
    cfg_factory,
) -> None:
    cfg = cfg_factory("per_holding", per_band=300)
    drifts = compute_drift(
        "ACCT", per_holding_current, per_holding_targets, sample_prices, 100.0, cfg
    )
    symbols = [d.symbol for d in drifts]
    assert symbols == ["AAA", "BBB"]
    by_symbol = {d.symbol: d for d in drifts}
    assert by_symbol["AAA"].action == "SELL"
    assert by_symbol["BBB"].action == "BUY"
    assert "CCC" not in symbols and "DDD" not in symbols


def test_total_drift_mode_selects_largest_until_band(
    total_current,
    total_targets,
    sample_prices,
    cfg_factory,
) -> None:
    cfg = cfg_factory("total_drift", total_band=500)
    drifts = compute_drift(
        "ACCT", total_current, total_targets, sample_prices, 100.0, cfg
    )
    assert [d.symbol for d in drifts] == ["AAA", "BBB"]
    by_symbol = {d.symbol: d for d in drifts}
    assert by_symbol["AAA"].action == "SELL"
    assert by_symbol["BBB"].action == "BUY"


def test_prioritize_by_drift_filters_and_sorts(cfg_factory) -> None:
    drifts = [
        Drift("AAA", 0.0, 0.0, 0.0, 50.0, "BUY"),
        Drift("BBB", 0.0, 0.0, 0.0, -200.0, "SELL"),
        Drift("CCC", 0.0, 0.0, 0.0, 150.0, "BUY"),
    ]
    cfg = cfg_factory(min_order=100)
    prioritized = prioritize_by_drift("ACCT", drifts, cfg)
    assert [d.symbol for d in prioritized] == ["BBB", "CCC"]
    assert prioritized[0].drift_usd == -200.0
    assert prioritized[1].drift_usd == 150.0


def test_compute_drift_zero_drift_returns_hold() -> None:
    current = {"AAA": 5}
    targets = {"AAA": 100.0}
    prices = {"AAA": 1.0}
    net_liq = 5.0
    drifts = compute_drift("ACCT", current, targets, prices, net_liq, cfg=None)
    assert len(drifts) == 1
    d = drifts[0]
    assert d.drift_pct == pytest.approx(0.0)
    assert d.action == "HOLD"
