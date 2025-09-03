import csv
import logging
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.core.drift import Drift
from src.core.sizing import SizedTrade
from src.io.reporting import write_post_trade_report, write_pre_trade_report


def _cfg():
    return SimpleNamespace(
        execution=SimpleNamespace(order_type="MKT", algo_preference="none")
    )


def test_write_pre_and_post_trade_reports(tmp_path, caplog):
    caplog.set_level(logging.INFO)
    ts = datetime(2023, 1, 1)

    drift = Drift("AAA", 60.0, 50.0, -10.0, -1000.0, "BUY")
    trades = [SizedTrade("AAA", "BUY", 10.0, 1000.0)]
    prices = {"AAA": 100.0}
    cfg = _cfg()

    pre_path = write_pre_trade_report(
        tmp_path,
        ts,
        "ACCT",
        [drift],
        trades,
        prices,
        9000.0,
        0.9,
        10000.0,
        1.0,
        cfg,
    )

    expected_pre_fields = [
        "timestamp_run",
        "account_id",
        "symbol",
        "is_cash",
        "target_wt_pct",
        "current_wt_pct",
        "drift_pct",
        "drift_usd",
        "action",
        "qty_shares",
        "est_price",
        "order_type",
        "algo",
        "est_value_usd",
        "pre_gross_exposure",
        "post_gross_exposure",
        "pre_leverage",
        "post_leverage",
    ]

    with pre_path.open() as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == expected_pre_fields
        row = next(reader)

    numeric_fields = [
        "target_wt_pct",
        "current_wt_pct",
        "drift_pct",
        "drift_usd",
        "qty_shares",
        "est_price",
        "est_value_usd",
        "pre_gross_exposure",
        "post_gross_exposure",
        "pre_leverage",
        "post_leverage",
    ]

    expected_values = {
        "target_wt_pct": drift.target_wt_pct,
        "current_wt_pct": drift.current_wt_pct,
        "drift_pct": drift.drift_pct,
        "drift_usd": drift.drift_usd,
        "qty_shares": trades[0].quantity,
        "est_price": prices["AAA"],
        "est_value_usd": trades[0].notional,
        "pre_gross_exposure": 9000.0,
        "post_gross_exposure": 10000.0,
        "pre_leverage": 0.9,
        "post_leverage": 1.0,
    }

    for field in numeric_fields:
        assert float(row[field]) == pytest.approx(expected_values[field])

    results = [
        {
            "symbol": "AAA",
            "status": "Filled",
            "filled": 8.0,
            "avg_fill_price": 110.0,
            "fill_qty": 8.0,
            "fill_price": 110.0,
            "fill_time": ts.isoformat(),
            "commission": 1.23,
        }
    ]

    post_path = write_post_trade_report(
        tmp_path,
        ts,
        "ACCT",
        [drift],
        trades,
        results,
        prices,
        9000.0,
        0.9,
        10000.0,
        1.0,
        cfg,
    )

    expected_post_fields = expected_pre_fields + [
        "fill_qty",
        "fill_price",
        "fill_timestamp",
        "commission",
        "commission_placeholder",
        "status",
        "error",
        "notes",
    ]

    with post_path.open() as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == expected_post_fields
        row = next(reader)

    for field in numeric_fields:
        assert float(row[field]) == pytest.approx(expected_values[field])
    assert float(row["fill_qty"]) == pytest.approx(8.0)
    assert float(row["fill_price"]) == pytest.approx(110.0)
    assert row["fill_timestamp"] == ts.isoformat()
    assert float(row["commission"]) == pytest.approx(1.23)
    assert row["commission_placeholder"] == "False"

    messages = [rec.message for rec in caplog.records]
    assert f"Pre-trade report written to {pre_path}" in messages
    assert f"Post-trade report written to {post_path}" in messages
