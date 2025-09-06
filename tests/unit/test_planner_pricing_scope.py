from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import cast

from src.broker.ibkr_client import IBKRClient
from src.core.drift import Drift
from src.core.planner import plan_account
from src.io import AppConfig


def test_plan_account_fetches_only_needed_prices() -> None:
    class FakeClient(IBKRClient):
        def __init__(self) -> None:  # pragma: no cover - simple stub
            self._ib = object()

        async def __aenter__(self) -> "FakeClient":  # pragma: no cover - simple stub
            return self

        async def __aexit__(
            self, exc_type, exc, tb
        ) -> None:  # pragma: no cover - simple stub
            return None

        async def snapshot(self, account_id, *_, **__):
            return {
                "positions": [
                    {"symbol": "AAA", "position": 1.0, "market_price": 10.0},
                    {"symbol": "BBB", "position": 1.0},
                ],
                "cash": 0.0,
                "net_liq": 0.0,
            }

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
        "AAA": {"smurf": 1.0},
        "BBB": {"smurf": 1.0},
        "CCC": {"smurf": 1.0},
        "DDD": {"smurf": 0.0},
        "CASH": {},
    }

    fetched: list[str] = []

    async def fake_fetch_price(ib, symbol, cfg):
        fetched.append(symbol)
        return symbol, 1.0

    def fake_compute_drift(account_id, current, targets, prices, net_liq, cfg):
        return [
            Drift("AAA", 0, 0, -1.0, -1.0, prices["AAA"], "BUY"),
            Drift("BBB", 0, 0, -1.0, -1.0, prices["BBB"], "BUY"),
            Drift("CCC", 0, 0, -1.0, -1.0, prices["CCC"], "BUY"),
        ]

    asyncio.run(
        plan_account(
            "A",
            portfolios,
            cfg,
            datetime.now(),
            client_factory=FakeClient,
            compute_drift=fake_compute_drift,
            prioritize_by_drift=lambda account_id, drifts, cfg: drifts,
            size_orders=lambda *args, **kwargs: ([], 0.0, 0.0),
            fetch_price=fake_fetch_price,
            render_preview=lambda *args, **kwargs: "",
            write_pre_trade_report=lambda *args, **kwargs: None,
        )
    )

    assert sorted(fetched) == ["BBB", "CCC"]


def test_plan_account_fetches_price_for_avg_cost_position() -> None:
    """Positions reporting only average cost should trigger price fetch."""

    class FakeClient(IBKRClient):
        def __init__(self) -> None:  # pragma: no cover - simple stub
            self._ib = object()

        async def __aenter__(self) -> "FakeClient":  # pragma: no cover - simple stub
            return self

        async def __aexit__(
            self, exc_type, exc, tb
        ) -> None:  # pragma: no cover - simple stub
            return None

        async def snapshot(self, account_id, *_, **__):
            return {
                "positions": [
                    {"symbol": "AAA", "position": 1.0, "avg_cost": 10.0},
                ],
                "cash": 0.0,
                "net_liq": 0.0,
            }

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
        "AAA": {"smurf": 1.0},
        "CASH": {},
    }

    fetched: list[str] = []

    async def fake_fetch_price(ib, symbol, cfg):
        fetched.append(symbol)
        return symbol, 1.0

    def fake_compute_drift(account_id, current, targets, prices, net_liq, cfg):
        return [
            Drift("AAA", 0, 0, -1.0, -1.0, prices["AAA"], "BUY"),
        ]

    asyncio.run(
        plan_account(
            "A",
            portfolios,
            cfg,
            datetime.now(),
            client_factory=FakeClient,
            compute_drift=fake_compute_drift,
            prioritize_by_drift=lambda account_id, drifts, cfg: drifts,
            size_orders=lambda *args, **kwargs: ([], 0.0, 0.0),
            fetch_price=fake_fetch_price,
            render_preview=lambda *args, **kwargs: "",
            write_pre_trade_report=lambda *args, **kwargs: None,
        )
    )

    assert fetched == ["AAA"]
