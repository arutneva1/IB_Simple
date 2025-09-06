from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import cast

import pytest

from src.broker.ibkr_client import IBKRClient
from src.core.planner import plan_account
from src.io import AppConfig


def test_plan_account_builds_targets_from_mix() -> None:
    """plan_account computes targets using model mix values."""

    class FakeClient(IBKRClient):
        def __init__(self) -> None:  # pragma: no cover - simple stub
            self._ib = object()

        async def __aenter__(self) -> "FakeClient":  # pragma: no cover - simple stub
            return self

        async def __aexit__(
            self, exc_type, exc, tb
        ) -> None:  # pragma: no cover - simple stub
            return None

        async def snapshot(self, account_id):
            return {
                "positions": [
                    {"symbol": "AAA", "position": 0.0, "market_price": 1.0},
                    {"symbol": "BBB", "position": 0.0, "market_price": 1.0},
                    {"symbol": "CCC", "position": 0.0, "market_price": 1.0},
                ],
                "cash": 0.0,
                "net_liq": 0.0,
            }

    cfg = cast(
        AppConfig,
        SimpleNamespace(
            ibkr=SimpleNamespace(host="h", port=1, client_id=1),
            models=SimpleNamespace(smurf=0.6, badass=0.2, gltr=0.2),
            pricing=SimpleNamespace(price_source="last", fallback_to_snapshot=True),
            io=SimpleNamespace(report_dir="reports", log_level="INFO"),
        ),
    )

    portfolios = {
        "AAA": {"smurf": 100.0},
        "BBB": {"badass": 100.0},
        "CCC": {"gltr": 100.0},
        "CASH": {},
    }

    async def fake_fetch_price(*args, **kwargs):
        return "", 0.0

    plan = asyncio.run(
        plan_account(
            "A",
            portfolios,
            cfg,
            datetime.now(),
            client_factory=FakeClient,
            compute_drift=lambda *args, **kwargs: [],
            prioritize_by_drift=lambda *args, **kwargs: [],
            size_orders=lambda *args, **kwargs: ([], 0.0, 0.0),
            fetch_price=fake_fetch_price,
            render_preview=lambda *args, **kwargs: "",
            write_pre_trade_report=lambda *args, **kwargs: None,
        )
    )

    targets = plan["targets"]
    assert targets["AAA"] == pytest.approx(60.0)
    assert targets["BBB"] == pytest.approx(20.0)
    assert targets["CCC"] == pytest.approx(20.0)
    assert "CASH" not in targets
    assert sum(targets.values()) == pytest.approx(100.0)
