import asyncio
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.confirmation import confirm_global  # noqa: E402
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


def _drift(symbol: str, usd: float, net_liq: float, price: float) -> Drift:
    pct = usd / net_liq * 100.0
    action = "BUY" if usd < 0 else "SELL" if usd > 0 else "HOLD"
    current = 0.0
    target = -pct
    return Drift(symbol, target, current, pct, usd, price, action)


def test_overrides_affect_only_target_account():
    net_liq = 1000.0
    prices = {"AAA": 7.0, "BBB": 30.0}
    drifts = [
        _drift("AAA", -30.0, net_liq, prices["AAA"]),
        _drift("BBB", -80.0, net_liq, prices["BBB"]),
    ]
    cfg = _cfg()

    trades1, _, _ = size_orders(
        "ACC1", drifts, prices, {}, cash=200.0, net_liq=net_liq, cfg=cfg
    )
    trades2, _, _ = size_orders(
        "ACC2", drifts, prices, {}, cash=200.0, net_liq=net_liq, cfg=cfg
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


def test_confirm_global_respects_fractional_override():
    net_liq = 1000.0
    prices = {"AAA": 7.0, "BBB": 30.0}
    drifts = [
        _drift("AAA", -30.0, net_liq, prices["AAA"]),
        _drift("BBB", -80.0, net_liq, prices["BBB"]),
    ]
    cfg = _cfg()
    cfg.io = SimpleNamespace(report_dir=".")

    trades1, _, _ = size_orders(
        "ACC1", drifts, prices, {}, cash=200.0, net_liq=net_liq, cfg=cfg
    )
    trades2, _, _ = size_orders(
        "ACC2", drifts, prices, {}, cash=200.0, net_liq=net_liq, cfg=cfg
    )

    plan1 = {
        "account_id": "ACC1",
        "trades": trades1,
        "table": "ACC1",
        "pre_leverage": 1.0,
        "post_leverage": 1.0,
    }
    plan2 = {
        "account_id": "ACC2",
        "trades": trades2,
        "table": "ACC2",
        "pre_leverage": 1.0,
        "post_leverage": 1.0,
    }

    class DummyClient:
        pass

    async def dummy_submit_batch(*args, **kwargs):  # pragma: no cover - stub
        return []

    asyncio.run(
        confirm_global(
            [plan1, plan2],
            SimpleNamespace(dry_run=True, read_only=False, yes=True),
            cfg,
            datetime.now(),
            client_factory=DummyClient,
            submit_batch=dummy_submit_batch,
            append_run_summary=lambda *a, **k: None,
            write_post_trade_report=lambda *a, **k: None,
            compute_drift=lambda *a, **k: None,
            prioritize_by_drift=lambda *a, **k: None,
            size_orders=lambda *a, **k: ([], 0.0, 0.0),
        )
    )

    trades1_sorted = sorted(plan1["trades"], key=lambda t: t.symbol)
    assert len(trades1_sorted) == 2
    t_aaa, t_bbb = trades1_sorted
    assert t_aaa.quantity == pytest.approx(30.0 / 7.0)
    assert t_bbb.quantity == pytest.approx(80.0 / 30.0)

    assert len(plan2["trades"]) == 1
    t2 = plan2["trades"][0]
    assert t2.quantity == pytest.approx(2.0)
