"""Tests for sizing logic."""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
import math
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


def test_greedy_fill_under_limited_cash() -> None:
    net_liq = 1000.0
    drifts = [_drift("AAA", -150.0, net_liq), _drift("BBB", -100.0, net_liq)]
    prices = {"AAA": 24.0, "BBB": 10.0}
    cfg = _cfg(cash_buffer_pct=0.1, allow_fractional=True)

    trades, gross, lev = size_orders(drifts, prices, cash=200.0, cfg=cfg)

    qty = 100.0 / prices["AAA"]  # all available cash goes to highest priority
    assert trades == [SizedTrade("AAA", "BUY", qty, 100.0)]
    assert gross == 900.0
    assert lev == 0.9


def test_leverage_scaled_when_exceeding_max() -> None:
    net_liq = 1000.0
    drifts = [_drift("AAA", -100.0, net_liq), _drift("BBB", -100.0, net_liq)]
    prices = {"AAA": 10.0, "BBB": 10.0}
    cfg = _cfg(max_leverage=0.85)

    trades, gross, lev = size_orders(drifts, prices, cash=200.0, cfg=cfg)

    assert trades == [SizedTrade("AAA", "BUY", 5.0, 50.0)]
    assert gross == 850.0
    assert lev == 0.85


def test_rounds_and_drops_orders_below_min() -> None:
    net_liq = 1000.0
    drifts = [_drift("AAA", -80.0, net_liq)]
    prices = {"AAA": 45.0}
    cfg = _cfg(min_order_usd=50, allow_fractional=False)

    trades, gross, lev = size_orders(drifts, prices, cash=600.0, cfg=cfg)

    assert trades == []
    assert gross == 400.0  # exposure unchanged
    assert lev == 0.4


def test_rejects_non_finite_price_or_quantity() -> None:
    cfg = _cfg(allow_fractional=True)

    # Non-finite price
    net_liq = 1000.0
    drifts = [_drift("AAA", -100.0, net_liq)]
    prices = {"AAA": math.nan}
    with pytest.raises(ValueError):
        size_orders(drifts, prices, cash=200.0, cfg=cfg)

    # Non-finite quantity
    bad_drift = Drift("BBB", 0.0, 0.0, 0.0, math.nan, "BUY")
    prices = {"BBB": 10.0}
    with pytest.raises(ValueError):
        size_orders([bad_drift], prices, cash=200.0, cfg=cfg)
