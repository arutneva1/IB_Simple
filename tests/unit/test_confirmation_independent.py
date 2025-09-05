import asyncio
import sys
from argparse import Namespace
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

import src.rebalance as rebalance


class DummyClient:
    async def connect(self, host, port, client_id):  # noqa: ARG002
        return None

    async def disconnect(self, host, port, client_id):  # noqa: ARG002
        return None

    async def snapshot(self, account_id):  # noqa: ARG001
        return {"positions": [], "cash": 0.0, "net_liq": 0.0}


async def fake_load_portfolios(paths, *, host, port, client_id):  # noqa: ARG001
    return {aid: {} for aid in paths}


def _patch_common(monkeypatch: pytest.MonkeyPatch, tmp_path, records, executed):
    monkeypatch.setattr(rebalance, "IBKRClient", lambda: DummyClient())
    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)
    monkeypatch.setattr(rebalance, "compute_drift", lambda *a, **k: [])
    monkeypatch.setattr(rebalance, "prioritize_by_drift", lambda *a, **k: [])
    monkeypatch.setattr(rebalance, "size_orders", lambda *a, **k: ([], 0.0, 0.0))
    monkeypatch.setattr(rebalance, "render_preview", lambda *a, **k: "TABLE")
    monkeypatch.setattr(
        rebalance, "write_pre_trade_report", lambda *a, **k: tmp_path / "pre.csv"
    )

    async def fake_submit_batch(client, trades, cfg, account_id):  # noqa: ARG001
        executed.append(account_id)
        return []

    monkeypatch.setattr(rebalance, "submit_batch", fake_submit_batch)

    def fake_append(report_dir, ts, row):  # noqa: ARG001
        records.append(row)
        return tmp_path / "summary.csv"

    monkeypatch.setattr(rebalance, "append_run_summary", fake_append)
    monkeypatch.setattr(
        rebalance, "write_post_trade_report", lambda *a, **k: tmp_path / "post.csv"
    )
    monkeypatch.setattr(rebalance, "setup_logging", lambda *a, **k: None)

    async def fake_sleep(duration):  # noqa: ARG001
        pass

    monkeypatch.setattr(rebalance.asyncio, "sleep", fake_sleep)


def test_independent_confirmation_statuses(monkeypatch, tmp_path, portfolios_csv_path: Path):
    records: list[dict[str, str]] = []
    executed: list[str] = []
    _patch_common(monkeypatch, tmp_path, records, executed)

    responses = iter(["y", "n"])

    async def fake_prompt(prompt: str) -> str:  # pragma: no cover - trivial
        return next(responses)

    monkeypatch.setattr("src.core.confirmation._prompt_user", fake_prompt)

    args = Namespace(
        config="config/settings.ini",
        csv=str(portfolios_csv_path),
        dry_run=False,
        yes=False,
        read_only=False,
    )

    asyncio.run(rebalance._run(args))

    assert executed == ["DU111111"]
    assert len(records) == 2
    statuses = {r["account_id"]: r["status"] for r in records}
    assert statuses["DU111111"] == "completed"
    assert statuses["DU222222"] == "aborted"
