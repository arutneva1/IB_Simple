import argparse
import asyncio
import sys
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace

sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.core.drift import compute_drift


async def _run_rebalance(monkeypatch):
    rebalance = import_module("src.rebalance")
    cfg = SimpleNamespace(
        ibkr=SimpleNamespace(host="h", port=1, client_id=1),
        models=SimpleNamespace(smurf=0.5, badass=0.3, gltr=0.2),
        pricing=SimpleNamespace(price_source="last", fallback_to_snapshot=True),
        execution=SimpleNamespace(
            order_type="MKT", algo_preference="adaptive", commission_report_timeout=5.0
        ),
        io=SimpleNamespace(report_dir="reports", log_level="INFO"),
        accounts=SimpleNamespace(ids=["acct1", "bad", "acct2"]),
        rebalance=SimpleNamespace(min_order_usd=0),
        portfolio_paths={"acct1": Path("p1.csv"), "acct2": Path("p2.csv")},
    )
    monkeypatch.setattr(rebalance, "load_config", lambda _p: cfg)

    async def fake_load_portfolios(paths, *, host, port, client_id):  # noqa: ARG001
        data = {
            "acct1": {"AAA": {"smurf": 0.5, "badass": 0.3, "gltr": 0.2}},
            "acct2": {"BBB": {"smurf": 0.5, "badass": 0.3, "gltr": 0.2}},
        }
        return {aid: data.get(aid, {}) for aid in paths}

    monkeypatch.setattr(rebalance, "load_portfolios", fake_load_portfolios)

    snapshots = {
        "acct1": {
            "positions": [{"symbol": "AAA", "position": 1, "market_price": 10.0}],
            "cash": 100.0,
            "net_liq": 110.0,
        },
        "bad": {
            "positions": [{"symbol": "AAA", "position": 1, "market_price": 10.0}],
            "cash": 100.0,
            "net_liq": 110.0,
        },
        "acct2": {
            "positions": [{"symbol": "BBB", "position": 1, "market_price": 10.0}],
            "cash": 100.0,
            "net_liq": 110.0,
        },
    }

    snap_calls: list[str] = []

    class FakeClient:
        def __init__(self):
            self._ib = object()

        async def connect(self, host, port, client_id):  # pragma: no cover - trivial
            return None

        async def disconnect(self, host, port, client_id):  # pragma: no cover - trivial
            return None

        async def snapshot(self, account_id):
            snap_calls.append(account_id)
            return snapshots[account_id]

    monkeypatch.setattr(rebalance, "IBKRClient", lambda: FakeClient())

    async def fake_fetch_price(ib, symbol, cfg):  # noqa: ARG001
        return symbol, 10.0

    monkeypatch.setattr(rebalance, "_fetch_price", fake_fetch_price)
    monkeypatch.setattr(rebalance, "render_preview", lambda *a, **k: "TABLE")
    monkeypatch.setattr(rebalance, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(
        rebalance, "write_pre_trade_report", lambda *a, **k: Path("pre")
    )

    size_calls: list[str] = []

    def fake_size_orders(
        account_id, prioritized, prices, current_positions, cash, net_liq, cfg
    ):
        size_calls.append(account_id)
        return [], 0.0, 0.0

    monkeypatch.setattr(rebalance, "size_orders", fake_size_orders)
    monkeypatch.setattr(
        rebalance,
        "prioritize_by_drift",
        lambda account_id, drifts, cfg: drifts,
    )

    real_compute = compute_drift
    drift_calls: dict[str, int] = {}
    drift_results: dict[str, list] = {}

    def fake_compute(account_id, current, targets, prices, net_liq, cfg):
        drift_calls[account_id] = drift_calls.get(account_id, 0) + 1
        if account_id == "bad":
            raise ValueError("boom")
        result = real_compute(account_id, current, targets, prices, net_liq, cfg)
        drift_results[account_id] = result
        return result

    monkeypatch.setattr(rebalance, "compute_drift", fake_compute)

    def build_inputs(account_id):
        snap = snapshots[account_id]
        current = {p["symbol"]: float(p["position"]) for p in snap["positions"]}
        current["CASH"] = float(snap["cash"])
        prices = {
            p["symbol"]: float(p.get("market_price") or p.get("avg_cost"))
            for p in snap["positions"]
        }
        if account_id == "acct1":
            targets = {"AAA": 0.38}
        else:
            targets = {"BBB": 0.38}
        # ensure prices for target symbols
        prices.setdefault("AAA", 10.0)
        prices.setdefault("BBB", 10.0)
        return current, targets, prices, float(snap["net_liq"])

    expected = {}
    for acct in ("acct1", "acct2"):
        current, targets, prices, net_liq = build_inputs(acct)
        expected[acct] = real_compute(acct, current, targets, prices, net_liq, cfg)

    args = argparse.Namespace(
        config="cfg", csv="csv", dry_run=True, yes=False, read_only=False
    )
    failures = await rebalance._run(args)
    return snap_calls, drift_calls, drift_results, expected, size_calls, failures


def test_rebalance_plans_each_account(monkeypatch):
    snap_calls, drift_calls, drift_results, expected, size_calls, failures = (
        asyncio.run(_run_rebalance(monkeypatch))
    )

    assert snap_calls == ["acct1", "bad", "acct2"]
    assert drift_calls == {"acct1": 1, "bad": 1, "acct2": 1}
    assert size_calls == ["acct1", "acct2"]
    assert failures == [("bad", "boom")]
    assert drift_results["acct1"] == expected["acct1"]
    assert drift_results["acct2"] == expected["acct2"]
