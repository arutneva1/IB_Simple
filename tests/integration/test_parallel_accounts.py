import asyncio
import csv
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.rebalance as rebalance

pytestmark = pytest.mark.integration


class DummyClient:
    instances: list["DummyClient"] = []

    def __init__(self) -> None:
        DummyClient.instances.append(self)

    async def connect(
        self, host: str, port: int, client_id: int
    ) -> None:  # noqa: ARG002
        pass

    async def disconnect(
        self, host: str, port: int, client_id: int
    ) -> None:  # noqa: ARG002
        pass


async def fake_load_portfolios(csv_path, host, port, client_id):  # noqa: ARG001
    return {}


async def stub_plan_account(
    account_id, portfolios, cfg, ts_dt, **kwargs
):  # noqa: ARG001, D401
    client_factory = kwargs.get("client_factory", rebalance.IBKRClient)
    client_factory()
    await asyncio.sleep(0.1)
    return {
        "account_id": account_id,
        "table": "",
        "trades": [],
        "drifts": [],
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


async def stub_confirm_per_account(
    plan,
    args,
    cfg,
    ts_dt,
    *,
    client_factory,
    submit_batch,  # noqa: ARG002
    append_run_summary,
    write_post_trade_report,  # noqa: ARG002
    compute_drift,  # noqa: ARG002
    prioritize_by_drift,  # noqa: ARG002
    size_orders,  # noqa: ARG002
):
    client_factory()
    await asyncio.sleep(0.1)
    append_run_summary(
        Path(cfg.io.report_dir),
        ts_dt,
        {
            "timestamp_run": ts_dt.isoformat(),
            "account_id": plan["account_id"],
            "planned_orders": 0,
            "submitted": 0,
            "filled": 0,
            "rejected": 0,
            "buy_usd": 0.0,
            "sell_usd": 0.0,
            "pre_leverage": 0.0,
            "post_leverage": 0.0,
            "status": "ok",
            "error": "",
        },
    )


def test_parallel_accounts(monkeypatch, tmp_path):
    monkeypatch.setattr(rebalance, "IBKRClient", DummyClient)
    monkeypatch.setattr(rebalance, "plan_account", stub_plan_account)
    monkeypatch.setattr(rebalance, "confirm_per_account", stub_confirm_per_account)
    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)

    original_load_config = rebalance.load_config

    def fake_load_config(path):
        cfg = original_load_config(path)
        cfg.accounts.ids = ["DU111111", "DU222222"]
        cfg.accounts.parallel = True
        cfg.accounts.pacing_sec = 0.0
        cfg.io.report_dir = str(tmp_path / "reports")
        return cfg

    monkeypatch.setattr(rebalance, "load_config", fake_load_config)

    args = SimpleNamespace(
        config="config/settings.ini",
        csv="data/portfolios.csv",
        dry_run=True,
        yes=False,
        read_only=False,
        parallel_accounts=False,
    )

    start = time.perf_counter()
    asyncio.run(rebalance._run(args))
    duration = time.perf_counter() - start
    assert duration < 0.3

    assert len({id(c) for c in DummyClient.instances}) == len(DummyClient.instances)

    report_files = list((tmp_path / "reports").glob("run_summary_*.csv"))
    assert len(report_files) == 1
    with report_files[0].open() as fh:
        rows = list(csv.DictReader(fh))
    assert [row["account_id"] for row in rows] == ["DU111111", "DU222222"]
