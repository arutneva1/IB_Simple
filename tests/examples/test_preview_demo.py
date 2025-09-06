"""Example usage of src.core.preview.render as a test."""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.core.drift import Drift
from src.core.preview import render
from src.core.sizing import SizedTrade


def test_preview_demo_example() -> None:
    sample_plan = [
        Drift("AAA", 50.0, 60.0, 10.0, 640.0, "SELL"),
        Drift("BBB", 50.0, 40.0, -10.0, -640.0, "BUY"),
    ]
    sample_trades = [
        SizedTrade("AAA", "SELL", 6.4, 640.0),
        SizedTrade("BBB", "BUY", 7.111111, 640.0),
    ]
    pre_exp = 1000.0
    pre_lev = 1.0
    post_exp = pre_exp - 640.0 + 640.0
    post_lev = post_exp / (pre_exp / pre_lev)

    table = render(
        "DEMO",
        sample_plan,
        sample_trades,
        pre_exp,
        pre_lev,
        post_exp,
        post_lev,
    )

    assert "Batch Summary" in table
    assert "AAA" in table
    assert "BBB" in table
    assert "BUY" in table and "SELL" in table
