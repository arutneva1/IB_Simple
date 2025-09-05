import asyncio
import csv
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.rebalance as rebalance

pytestmark = pytest.mark.integration

confirm_starts: list[float] = []


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


async def fake_load_portfolios(path_map, host, port, client_id):  # noqa: ARG001
    return {aid: {} for aid in path_map}


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
    output_lock=None,  # noqa: ARG002
):
    assert output_lock is not None
    confirm_starts.append(time.perf_counter())
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
    assert duration < 0.4
    assert confirm_starts[1] - confirm_starts[0] >= 0.1

    assert len({id(c) for c in DummyClient.instances}) == len(DummyClient.instances)

    report_files = list((tmp_path / "reports").glob("run_summary_*.csv"))
    assert len(report_files) == 1
    with report_files[0].open() as fh:
        rows = list(csv.DictReader(fh))
    assert [row["account_id"] for row in rows] == ["DU111111", "DU222222"]


def test_serialized_confirmation_output(monkeypatch, capsys, tmp_path):
    """Exceptions during serialized confirmation print atomically."""

    monkeypatch.setattr(rebalance, "IBKRClient", DummyClient)
    monkeypatch.setattr(rebalance, "plan_account", stub_plan_account)
    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)

    async def noisy_confirm(
        plan,
        args,
        cfg,
        ts_dt,
        *,
        client_factory,
        submit_batch,  # noqa: ARG002
        append_run_summary,  # noqa: ARG002
        write_post_trade_report,  # noqa: ARG002
        compute_drift,  # noqa: ARG002
        prioritize_by_drift,  # noqa: ARG002
        size_orders,  # noqa: ARG002
        output_lock=None,
    ):
        assert output_lock is not None

        async def background() -> None:
            await rebalance._print_err("[yellow]noise[/yellow]", output_lock)

        asyncio.create_task(background())
        raise RuntimeError("boom")

    monkeypatch.setattr(rebalance, "confirm_per_account", noisy_confirm)

    original_load_config = rebalance.load_config

    def fake_load_config(path):
        cfg = original_load_config(path)
        cfg.accounts.ids = ["DU111111", "DU222222"]
        cfg.accounts.parallel = True
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

    asyncio.run(rebalance._run(args))

    lines = capsys.readouterr().out.splitlines()
    noise_lines = [l for l in lines if "noise" in l]
    error_lines = [l for l in lines if "boom" in l]
    assert noise_lines and error_lines
    for l in lines:
        assert not ("noise" in l and "boom" in l)
