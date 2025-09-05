"""Tests for resolving CSV paths relative to the config file."""

import asyncio
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

import src.rebalance as rebalance
from src.io.config_loader import ConfirmMode
from src.io.config_loader import load_config as real_load_config
from tests.unit.test_config_loader import VALID_CONFIG


def test_csv_path_resolved_relative_to_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, Path] = {}

    async def fake_load_portfolios(path_map, *, host, port, client_id):  # noqa: ARG001
        captured.update(path_map)
        return {aid: {} for aid in path_map}

    async def fake_plan_account(
        account_id, portfolios, cfg, ts_dt, **kwargs
    ):  # noqa: ARG001
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

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "settings.ini"
    cfg_path.write_text(VALID_CONFIG)
    csv_path = tmp_path / "default.csv"
    csv_path.write_text("")

    def fake_load_config(_path):  # noqa: ARG001
        cfg = real_load_config(cfg_path)
        cfg.accounts.pacing_sec = 0.0
        cfg.accounts.confirm_mode = ConfirmMode.GLOBAL
        cfg.io.report_dir = str(tmp_path)
        return cfg

    monkeypatch.setattr(rebalance, "load_config", fake_load_config)

    args = Namespace(
        config=str(cfg_path),
        csv="../default.csv",
        dry_run=True,
        yes=True,
        read_only=False,
        confirm_mode=None,
        parallel_accounts=False,
    )

    asyncio.run(rebalance._run(args))

    expected = csv_path.resolve()
    assert captured == {"ACC1": expected, "ACC2": expected}


def test_default_csv_path_from_config(
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

    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "settings.ini"
    cfg_content = VALID_CONFIG.replace(
        "[accounts]\nids = ACC1, ACC2\n",
        "[accounts]\nids = ACC1, ACC2\npath = default.csv\n",
    )
    cfg_path.write_text(cfg_content)
    csv_path = cfg_dir / "default.csv"
    csv_path.write_text("")

    def fake_load_config(_path):  # noqa: ARG001
        cfg = real_load_config(cfg_path)
        cfg.accounts.pacing_sec = 0.0
        cfg.accounts.confirm_mode = ConfirmMode.GLOBAL
        cfg.io.report_dir = str(tmp_path)
        return cfg

    monkeypatch.setattr(rebalance, "load_config", fake_load_config)

    args = Namespace(
        config=str(cfg_path),
        csv=None,
        dry_run=True,
        yes=True,
        read_only=False,
        confirm_mode=None,
        parallel_accounts=False,
    )

    asyncio.run(rebalance._run(args))

    expected = csv_path.resolve()
    assert captured == {"ACC1": expected, "ACC2": expected}
