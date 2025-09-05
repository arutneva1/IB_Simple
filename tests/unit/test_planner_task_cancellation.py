from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import cast

import pytest

from src.broker.ibkr_client import IBKRClient
from src.core.drift import Drift
from src.core.errors import PlanningError
from src.core.planner import plan_account
from src.io import AppConfig


def test_tasks_cancelled_on_unexpected_error() -> None:
    cancelled: set[str] = set()

    async def fake_fetch_price(ib, symbol, cfg):
        if symbol == "ERR":
            raise RuntimeError("boom")
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:  # pragma: no cover - safety
            cancelled.add(symbol)
            raise
        return symbol, 1.0

    def fake_compute_drift(account_id, current, targets, prices, net_liq, cfg):
        return [
            Drift("ERR", 0.0, 0.0, 0.0, 0.0, "BUY"),
            Drift("SLOW", 0.0, 0.0, 0.0, 0.0, "BUY"),
        ]

    def fake_prioritize(account_id, drifts, cfg):
        return drifts

    class FakeClient(IBKRClient):
        def __init__(self) -> None:
            self._ib = object()

        async def connect(self, host, port, client_id):
            return None

        async def disconnect(self, host, port, client_id):
            return None

        async def snapshot(self, account_id):
            return {"positions": [], "cash": 0.0, "net_liq": 0.0}

    cfg = cast(
        AppConfig,
        SimpleNamespace(
            ibkr=SimpleNamespace(host="h", port=1, client_id=1),
            models=SimpleNamespace(smurf=1.0, badass=0.0, gltr=0.0),
            pricing=SimpleNamespace(price_source="last", fallback_to_snapshot=True),
            io=SimpleNamespace(report_dir="reports", log_level="INFO"),
        ),
    )

    portfolios = {
        "ERR": {"smurf": 1.0, "badass": 0.0, "gltr": 0.0},
        "SLOW": {"smurf": 1.0, "badass": 0.0, "gltr": 0.0},
    }

    with pytest.raises(PlanningError):
        asyncio.run(
            plan_account(
                "A",
                portfolios,
                cfg,
                datetime.now(),
                client_factory=FakeClient,
                compute_drift=fake_compute_drift,
                prioritize_by_drift=fake_prioritize,
                size_orders=lambda *args, **kwargs: ([], 0.0, 0.0),
                fetch_price=fake_fetch_price,
                render_preview=lambda *args, **kwargs: "",
                write_pre_trade_report=lambda *args, **kwargs: None,
            )
        )

    assert "SLOW" in cancelled
