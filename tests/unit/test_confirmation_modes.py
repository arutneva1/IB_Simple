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

    async def snapshot(self, account_id):  # noqa: ARG002
        return {"positions": [], "cash": 0.0, "net_liq": 0.0}


async def fake_load_portfolios(path, *, host, port, client_id):  # noqa: ARG001
    return {}


def _patch_common(monkeypatch: pytest.MonkeyPatch, tmp_path):
    monkeypatch.setattr(rebalance, "IBKRClient", lambda: DummyClient())
    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)
    monkeypatch.setattr(rebalance, "compute_drift", lambda *a, **k: [])
    monkeypatch.setattr(rebalance, "prioritize_by_drift", lambda *a, **k: [])
    monkeypatch.setattr(
        rebalance,
        "size_orders",
        lambda *a, **k: ([], 0.0, 0.0),
    )
    monkeypatch.setattr(rebalance, "render_preview", lambda *a, **k: "TABLE")
    monkeypatch.setattr(
        rebalance,
        "write_pre_trade_report",
        lambda *a, **k: tmp_path / "pre.csv",
    )
    monkeypatch.setattr(rebalance, "append_run_summary", lambda *a, **k: None)
    monkeypatch.setattr(rebalance, "setup_logging", lambda *a, **k: None)


def test_per_account_prompts_once_per_account(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:  # pragma: no cover - trivial
        prompts.append(prompt)
        return "n"

    monkeypatch.setattr("builtins.input", fake_input)

    args = Namespace(
        config="config/settings.ini",
        csv="data/portfolios.csv",
        dry_run=False,
        yes=False,
        read_only=False,
    )

    asyncio.run(rebalance._run(args))

    assert prompts == ["Proceed? [y/N]: ", "Proceed? [y/N]: "]


def test_global_prompt_once_and_aborts(monkeypatch, tmp_path, capsys):
    records: list[dict[str, str]] = []

    def fake_append(report_dir, ts, row):  # noqa: ARG001
        records.append(row)
        return tmp_path / "summary.csv"

    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(rebalance, "append_run_summary", fake_append)

    prompts: list[str] = []

    def fake_input(prompt: str) -> str:  # pragma: no cover - trivial
        prompts.append(prompt)
        return "n"

    monkeypatch.setattr("builtins.input", fake_input)

    args = Namespace(
        config="config/settings.ini",
        csv="data/portfolios.csv",
        dry_run=False,
        yes=False,
        read_only=False,
        confirm_mode="global",
    )

    asyncio.run(rebalance._run(args))
    captured = capsys.readouterr().out

    assert prompts == ["Proceed? [y/N]: "]
    assert "Aborted by user." in captured
    assert len(records) == 2
    assert all(r["status"] == "aborted" for r in records)
