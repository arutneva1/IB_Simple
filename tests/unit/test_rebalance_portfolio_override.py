import asyncio
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

import src.rebalance as rebalance
from src.io.config_loader import ConfirmMode
from src.io.config_loader import load_config as real_load_config
from tests.unit.test_config_loader import VALID_CONFIG_WITH_ACCOUNT_PATH


def test_rebalance_uses_portfolio_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Path] = {}

    async def fake_load_portfolios(path_map, *, host, port, client_id):  # noqa: ARG001
        captured.update(path_map)
        return {aid: {} for aid in path_map}

    async def fake_plan_account(
        account_id, portfolios, cfg, ts_dt, **kwargs
    ):  # noqa: ANN001,ARG001
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

    async def fake_confirm_global(*args, **kwargs):  # noqa: ANN001,ARG001
        return []

    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)
    monkeypatch.setattr(rebalance, "plan_account", fake_plan_account)
    monkeypatch.setattr(rebalance, "confirm_global", fake_confirm_global)
    monkeypatch.setattr(rebalance, "setup_logging", lambda *a, **k: None)

    def fake_load_config(path):  # noqa: ARG001
        cfg_path = tmp_path / "settings.ini"
        cfg_path.write_text(VALID_CONFIG_WITH_ACCOUNT_PATH)
        (tmp_path / "foo.csv").write_text("")
        cfg = real_load_config(cfg_path)
        cfg.accounts.pacing_sec = 0.0
        cfg.accounts.confirm_mode = ConfirmMode.GLOBAL
        cfg.io.report_dir = str(tmp_path)
        cfg.portfolio_paths["ACC1"] = tmp_path / "p1.csv"
        return cfg

    monkeypatch.setattr(rebalance, "load_config", fake_load_config)

    default_csv = tmp_path / "default.csv"
    default_csv.write_text("")

    args = Namespace(
        config="config/settings.ini",
        csv=str(default_csv),
        dry_run=True,
        yes=True,
        read_only=False,
        confirm_mode=None,
        parallel_accounts=False,
    )

    asyncio.run(rebalance._run(args))

    assert captured == {"ACC1": tmp_path / "p1.csv", "ACC2": default_csv}
