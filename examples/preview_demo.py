"""Demonstration of :func:`src.core.preview.render`."""

from __future__ import annotations

from src.core.drift import Drift
from src.core.preview import render
from src.core.sizing import SizedTrade


def main() -> None:
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
    post_exp = pre_exp - 640.0 + 640.0  # no change in this demo
    post_lev = post_exp / (pre_exp / pre_lev)
    print(
        render(
            "DEMO",
            sample_plan,
            sample_trades,
            pre_exp,
            pre_lev,
            post_exp,
            post_lev,
        )
    )


if __name__ == "__main__":  # pragma: no cover - example script
    main()
