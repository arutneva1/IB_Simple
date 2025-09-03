"""Test handling of KeyboardInterrupt in rebalance.main."""

from __future__ import annotations

import sys

import pytest

import src.rebalance as rebalance


class DummyIBKRClient:
    """Stub client that raises KeyboardInterrupt during snapshot."""

    disconnected = False

    def __init__(self) -> None:
        type(self).disconnected = False

    async def connect(
        self, host: str, port: int, client_id: int
    ) -> None:  # noqa: ARG002
        return None

    async def disconnect(
        self, host: str, port: int, client_id: int
    ) -> None:  # noqa: ARG002
        type(self).disconnected = True
        return None

    async def snapshot(self, account_id: str) -> dict:  # noqa: ARG002
        raise KeyboardInterrupt


async def fake_load_portfolios(path, *, host, port, client_id):  # noqa: ARG001
    return {}


def test_main_handles_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch, capsys):
    monkeypatch.setattr(rebalance, "IBKRClient", DummyIBKRClient)
    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)
    monkeypatch.setattr(rebalance, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["rebalance"])

    with pytest.raises(SystemExit) as exc:
        rebalance.main()

    assert exc.value.code == 1
    captured = capsys.readouterr().out
    assert "Aborted" in captured
    assert DummyIBKRClient.disconnected
