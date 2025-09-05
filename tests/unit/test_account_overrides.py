import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.drift import Drift  # noqa: E402
from src.core.sizing import size_orders  # noqa: E402
from src.io.config_loader import AccountOverride  # noqa: E402


def _cfg():
    reb = SimpleNamespace(
        min_order_usd=50,
        allow_fractional=False,
        cash_buffer_type="pct",
        cash_buffer_pct=0.0,
        cash_buffer_abs=0.0,
        max_leverage=2.0,
    )
    overrides = {"ACC1": AccountOverride(allow_fractional=True, min_order_usd=10)}
    return SimpleNamespace(rebalance=reb, account_overrides=overrides)


def _drift(symbol: str, usd: float, net_liq: float) -> Drift:
    pct = usd / net_liq * 100.0
    action = "BUY" if usd < 0 else "SELL" if usd > 0 else "HOLD"
    current = 0.0
    target = -pct
    return Drift(symbol, target, current, pct, usd, action)


def test_overrides_affect_only_target_account():
    net_liq = 1000.0
    drifts = [_drift("AAA", -30.0, net_liq), _drift("BBB", -80.0, net_liq)]
    prices = {"AAA": 7.0, "BBB": 30.0}
    cfg = _cfg()

    trades1, _, _ = size_orders(
        "ACC1", drifts, prices, cash=200.0, net_liq=net_liq, cfg=cfg
    )
    trades2, _, _ = size_orders(
        "ACC2", drifts, prices, cash=200.0, net_liq=net_liq, cfg=cfg
    )

    trades1_sorted = sorted(trades1, key=lambda t: t.symbol)
    assert len(trades1_sorted) == 2
    t_aaa, t_bbb = trades1_sorted
    assert t_aaa.symbol == "AAA"
    assert t_aaa.action == "BUY"
    assert t_aaa.notional == pytest.approx(30.0)
    assert t_aaa.quantity == pytest.approx(30.0 / 7.0)
    assert t_bbb.symbol == "BBB"
    assert t_bbb.action == "BUY"
    assert t_bbb.notional == pytest.approx(80.0)
    assert t_bbb.quantity == pytest.approx(80.0 / 30.0)

    assert len(trades2) == 1
    t2 = trades2[0]
    assert t2.symbol == "BBB"
    assert t2.action == "BUY"
    assert t2.notional == pytest.approx(60.0)
    assert t2.quantity == pytest.approx(2.0)
