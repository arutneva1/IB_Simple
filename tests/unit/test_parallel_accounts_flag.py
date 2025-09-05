import asyncio
import time
from types import SimpleNamespace
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

import pytest

import src.rebalance as rebalance


def test_parallel_accounts_flag_overrides_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plan_starts: list[float] = []

    async def fake_load_portfolios(path_map, *, host, port, client_id):  # noqa: ARG001
        return {aid: {} for aid in path_map}

    async def stub_plan_account(account_id, portfolios, cfg, ts_dt, **kwargs):  # noqa: ARG001
        plan_starts.append(time.perf_counter())
        await asyncio.sleep(0.1)
        return {
            "account_id": account_id,
            "drifts": [],
            "trades": [],
            "prices": {},
            "current": {},
            "targets": {},
            "net_liq": 0.0,
            "pre_gross_exposure": 0.0,
            "pre_leverage": 0.0,
            "post_leverage": 0.0,
            "planned_orders": 0,
            "buy_usd": 0.0,
            "sell_usd": 0.0,
        }

    async def stub_confirm_per_account(*args, **kwargs):  # noqa: ANN001,ARG001
        return None

    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)
    monkeypatch.setattr(rebalance, "plan_account", stub_plan_account)
    monkeypatch.setattr(rebalance, "confirm_per_account", stub_confirm_per_account)
    monkeypatch.setattr(rebalance, "setup_logging", lambda *a, **k: None)

    original_load_config = rebalance.load_config
    cfg_holder: dict[str, object] = {}

    def fake_load_config(path):
        cfg = original_load_config(path)
        assert cfg.accounts.parallel is False
        cfg.accounts.pacing_sec = 0.0
        cfg.io.report_dir = str(tmp_path)
        cfg_holder["cfg"] = cfg
        return cfg

    monkeypatch.setattr(rebalance, "load_config", fake_load_config)

    args = SimpleNamespace(
        config="config/settings.ini",
        csv="data/portfolios.csv",
        dry_run=True,
        yes=False,
        read_only=False,
        parallel_accounts=True,
    )

    asyncio.run(rebalance._run(args))

    assert cfg_holder["cfg"].accounts.parallel is True
    assert len(plan_starts) == 2
    assert abs(plan_starts[1] - plan_starts[0]) < 0.1
