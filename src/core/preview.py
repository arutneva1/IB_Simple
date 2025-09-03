"""Render a drift preview table.

This module formats a list of :class:`~src.core.drift.Drift` records into a
human readable table.  It is intentionally presentation only and performs no
side effects beyond returning the rendered string.
"""

from __future__ import annotations

from typing import Mapping

from rich.console import Console
from rich.table import Table

from .drift import Drift
from .sizing import SizedTrade


def render(
    plan: list[Drift],
    trades: list[SizedTrade] | None = None,
    prices: Mapping[str, float] | None = None,
) -> str:
    """Return a formatted table for the given drift plan.

    Parameters
    ----------
    plan:
        Drift records, typically already filtered and prioritised.

    Returns
    -------
    str
        Table rendering of the drift information.
    """

    table = Table(show_header=True, header_style="bold")
    table.add_column("Symbol")
    table.add_column("Target %", justify="right")
    table.add_column("Current %", justify="right")
    table.add_column("Drift %", justify="right")
    table.add_column("Drift $", justify="right")
    table.add_column("Price", justify="right")
    table.add_column("Qty", justify="right")
    table.add_column("Action")

    qty_lookup = {t.symbol: t.quantity for t in (trades or [])}
    price_lookup = prices or {}

    for d in plan:
        qty = qty_lookup.get(d.symbol, 0.0)
        price = price_lookup.get(d.symbol)
        table.add_row(
            d.symbol,
            f"{d.target_wt_pct:.2f}",
            f"{d.current_wt_pct:.2f}",
            f"{d.drift_pct:.2f}",
            f"{d.drift_usd:.2f}",
            f"{price:.2f}" if price is not None else "-",
            f"{qty:.2f}",
            d.action,
        )

    from io import StringIO

    console = Console(file=StringIO(), record=True)
    console.print(table)
    return console.export_text()


if __name__ == "__main__":  # pragma: no cover - convenience demo
    sample_plan = [
        Drift("AAA", 50.0, 60.0, 10.0, 640.0, "SELL"),
        Drift("BBB", 50.0, 40.0, -10.0, -640.0, "BUY"),
    ]
    print(render(sample_plan, prices={"AAA": 100.0, "BBB": 90.0}))
