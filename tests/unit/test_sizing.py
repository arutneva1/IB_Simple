"""Tests for sizing logic."""

import math
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

# ``src.__init__`` imports ``ib_async`` which isn't required for these tests.
# The ``Any`` annotations silence mypy's attribute checks for these dummy modules.
ib_async: Any = ModuleType("ib_async")
ib_async.IB = object
contract_mod: Any = ModuleType("ib_async.contract")
contract_mod.Stock = object
ib_async.contract = contract_mod
sys.modules.setdefault("ib_async", ib_async)
sys.modules.setdefault("ib_async.contract", contract_mod)

from src.core.drift import Drift  # noqa: E402
from src.core.sizing import SizedTrade, size_orders  # noqa: E402


def _cfg(
    *,
    min_order_usd: int = 1,
    allow_fractional: bool = False,
    cash_buffer_type: str = "pct",
    cash_buffer_pct: float = 0.0,
    cash_buffer_abs: float = 0.0,
    max_leverage: float = 1.0,
):
    reb = SimpleNamespace(
        min_order_usd=min_order_usd,
        allow_fractional=allow_fractional,
        cash_buffer_type=cash_buffer_type,
        cash_buffer_pct=cash_buffer_pct,
        cash_buffer_abs=cash_buffer_abs,
        max_leverage=max_leverage,
    )
    return SimpleNamespace(rebalance=reb)


def _drift(symbol: str, usd: float, net_liq: float, price: float) -> Drift:
    pct = usd / net_liq * 100.0
    action = "BUY" if usd < 0 else "SELL" if usd > 0 else "HOLD"
    # The specific target/current weights are irrelevant for sizing; they only
    # need to differ by ``pct``.
    current = 0.0
    target = -pct
    return Drift(symbol, target, current, pct, usd, price, action)


@pytest.mark.parametrize(
    "cash_buffer_type,cash_buffer_pct,cash_buffer_abs",
    [("pct", 0.1, 0.0), ("abs", 0.0, 100.0)],
)
def test_greedy_fill_under_limited_cash(
    cash_buffer_type: str, cash_buffer_pct: float, cash_buffer_abs: float
) -> None:
    net_liq = 1000.0
    prices = {"AAA": 24.0, "BBB": 10.0}
    drifts = [
        _drift("AAA", -150.0, net_liq, prices["AAA"]),
        _drift("BBB", -100.0, net_liq, prices["BBB"]),
    ]
    cfg = _cfg(
        cash_buffer_type=cash_buffer_type,
        cash_buffer_pct=cash_buffer_pct,
        cash_buffer_abs=cash_buffer_abs,
        allow_fractional=True,
    )

    trades, gross, lev = size_orders(
        "ACCT", drifts, prices, {}, cash=200.0, net_liq=net_liq, cfg=cfg
    )

    qty = 100.0 / prices["AAA"]  # all available cash goes to highest priority
    assert trades == [SizedTrade("AAA", "BUY", qty, 100.0)]
    assert gross == 900.0
    assert lev == 0.9


def test_residual_cash_distributed_proportionally() -> None:
    """Leftover cash from sells is split among unmet buys proportionally."""
    net_liq = 1000.0
    prices = {"AAA": 10.0, "BBB": 20.0, "CCC": 5.0}
    drifts = [
        _drift("AAA", -100.0, net_liq, prices["AAA"]),
        _drift("BBB", -200.0, net_liq, prices["BBB"]),
        _drift("CCC", 300.0, net_liq, prices["CCC"]),
    ]
    cfg = _cfg()

    trades, gross, lev = size_orders(
        "ACCT", drifts, prices, {"CCC": 60.0}, cash=0.0, net_liq=net_liq, cfg=cfg
    )

    assert sorted(trades, key=lambda t: t.symbol) == [
        SizedTrade("AAA", "BUY", 10.0, 100.0),
        SizedTrade("BBB", "BUY", 10.0, 200.0),
        SizedTrade("CCC", "SELL", 60.0, 300.0),
    ]
    assert gross == 1000.0
    assert lev == 1.0


def test_leverage_scaled_when_exceeding_max() -> None:
    net_liq = 1000.0
    prices = {"AAA": 10.0, "BBB": 10.0}
    drifts = [
        _drift("AAA", -100.0, net_liq, prices["AAA"]),
        _drift("BBB", -100.0, net_liq, prices["BBB"]),
    ]
    cfg = _cfg(max_leverage=0.85)

    trades, gross, lev = size_orders(
        "ACCT", drifts, prices, {}, cash=200.0, net_liq=net_liq, cfg=cfg
    )

    assert trades == [SizedTrade("AAA", "BUY", 5.0, 50.0)]
    assert gross == 850.0
    assert lev == 0.85


def test_rounds_and_drops_orders_below_min() -> None:
    net_liq = 1000.0
    prices = {"AAA": 45.0}
    drifts = [_drift("AAA", -80.0, net_liq, prices["AAA"])]
    cfg = _cfg(min_order_usd=50, allow_fractional=False)

    trades, gross, lev = size_orders(
        "ACCT", drifts, prices, {}, cash=600.0, net_liq=net_liq, cfg=cfg
    )

    assert trades == []
    assert gross == 400.0  # exposure unchanged
    assert lev == 0.4


def test_rejects_non_finite_price_or_quantity() -> None:
    cfg = _cfg(allow_fractional=True)

    # Non-finite price
    net_liq = 1000.0
    drifts = [_drift("AAA", -100.0, net_liq, 100.0)]
    prices = {"AAA": math.nan}
    with pytest.raises(ValueError):
        size_orders("ACCT", drifts, prices, {}, cash=200.0, net_liq=net_liq, cfg=cfg)

    # Non-finite quantity
    bad_drift = Drift("BBB", 0.0, 0.0, 0.0, math.nan, 1.0, "BUY")
    prices = {"BBB": 10.0}
    with pytest.raises(ValueError):
        size_orders(
            "ACCT", [bad_drift], prices, {}, cash=200.0, net_liq=net_liq, cfg=cfg
        )


def test_duplicate_symbols_are_merged() -> None:
    """Trades for the same symbol are aggregated into a single entry."""
    net_liq = 1000.0
    prices = {"AAA": 10.0}
    drifts = [
        _drift("AAA", -150.0, net_liq, prices["AAA"]),
        _drift("AAA", -50.0, net_liq, prices["AAA"]),
    ]
    cfg = _cfg(allow_fractional=True)

    trades, _gross, _lev = size_orders(
        "ACCT", drifts, prices, {}, cash=500.0, net_liq=net_liq, cfg=cfg
    )

    assert trades == [SizedTrade("AAA", "BUY", 20.0, 200.0)]


def test_buy_qty_stable_on_price_drop() -> None:
    """Buys use snapshot price to determine share quantity after a drop."""
    net_liq = 1000.0
    drifts = [_drift("AAA", -1000.0, net_liq, 10.0)]
    prices = {"AAA": 5.0}  # price dropped from 10 to 5
    cfg = _cfg(allow_fractional=True)

    trades, gross, lev = size_orders(
        "ACCT", drifts, prices, {}, cash=1000.0, net_liq=net_liq, cfg=cfg
    )

    assert trades == [SizedTrade("AAA", "BUY", 100.0, 500.0)]
    assert gross == 500.0
    assert lev == 0.5


def test_sell_qty_capped_by_current_position_on_price_drop() -> None:
    """Sells never exceed existing shares when price falls after snapshot."""
    net_liq_for_drift = 1000.0
    drifts = [_drift("AAA", 1000.0, net_liq_for_drift, 10.0)]
    prices = {"AAA": 5.0}  # price dropped from 10 to 5
    cfg = _cfg(allow_fractional=True)

    trades, gross, lev = size_orders(
        "ACCT",
        drifts,
        prices,
        {"AAA": 100.0},
        cash=0.0,
        net_liq=500.0,
        cfg=cfg,
    )

    assert trades == [SizedTrade("AAA", "SELL", 100.0, 500.0)]
    assert gross == 0.0
    assert lev == 0.0
