import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import cast

from src.broker.ibkr_client import IBKRClient
from src.core.planner import plan_account
from src.io import AppConfig


def test_plan_account_refreshes_stale_prices(monkeypatch):
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
                    {"symbol": "AAA", "position": 1.0, "market_price": 10.0},
                ],
                "cash": 0.0,
                "net_liq": 0.0,
            }

    cfg = cast(
        AppConfig,
        SimpleNamespace(
            ibkr=SimpleNamespace(host="h", port=1, client_id=1),
            models=SimpleNamespace(smurf=1.0, badass=0.0, gltr=0.0),
            pricing=SimpleNamespace(
                price_source="last", fallback_to_snapshot=True, price_max_age_sec=30
            ),
            io=SimpleNamespace(report_dir="reports", log_level="INFO"),
        ),
    )

    fetched: list[str] = []

    async def fake_fetch_price(ib, symbol, cfg):
        fetched.append(symbol)
        return symbol, 10.0

    class FakeDateTime(datetime):
        calls = 0

        @classmethod
        def utcnow(cls):
            cls.calls += 1
            if cls.calls == 1:
                return datetime(2024, 1, 1, 0, 0, 0)
            return datetime(2024, 1, 1, 0, 0, 31)

    monkeypatch.setattr("src.core.planner.datetime", FakeDateTime)

    asyncio.run(
        plan_account(
            "A",
            {"AAA": {"smurf": 1.0}, "CASH": {}},
            cfg,
            datetime.now(),
            client_factory=FakeClient,
            compute_drift=lambda *args, **kwargs: [],
            prioritize_by_drift=lambda account_id, drifts, cfg: drifts,
            size_orders=lambda *args, **kwargs: ([], 0.0, 0.0),
            fetch_price=fake_fetch_price,
            render_preview=lambda *args, **kwargs: "",
            write_pre_trade_report=lambda *args, **kwargs: None,
        )
    )

    assert fetched == ["AAA"]

