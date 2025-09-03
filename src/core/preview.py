"""Render a drift preview table.

This module formats a list of :class:`~src.core.drift.Drift` records into a
human readable table.  It is intentionally presentation only and performs no
side effects beyond returning the rendered string.
"""

from __future__ import annotations

from io import StringIO

from rich import box
from rich.console import Console
from rich.table import Table

from .drift import Drift
from .sizing import SizedTrade


def render(
    plan: list[Drift],
    trades: list[SizedTrade] | None = None,
    pre_gross_exposure: float = 0.0,
    pre_leverage: float = 0.0,
    post_gross_exposure: float = 0.0,
    post_leverage: float = 0.0,
) -> str:
    """Return a formatted table for the given drift plan.

    Parameters
    ----------
    plan:
        Drift records, typically already filtered and prioritised.
    trades:
        Optional sized trade information used to display quantities and
        notionals.
    pre_gross_exposure:
        Portfolio gross exposure before applying the trades.
    pre_leverage:
        Portfolio leverage before applying the trades.
    post_gross_exposure:
        Projected portfolio gross exposure after applying the trades.
    post_leverage:
        Projected portfolio leverage after applying the trades.

    Returns
    -------
    str
        Table rendering of the drift information followed by a batch summary.
    """

    # ``Rich``'s default table box style has changed across releases. Some
    # versions render with the heavy box drawing characters we expect in the
    # unit tests while others fall back to a light or square style. Explicitly
    # request the ``HEAVY_HEAD`` box so the column separators are always the
    # heavy vertical bar (``\u2503``) regardless of the ``rich`` version.
    table = Table(
        show_header=True,
        header_style="bold",
        box=box.HEAVY_HEAD,  # ensure heavy vertical separators
    )
    table.add_column("Symbol")
    table.add_column("Target %", justify="right")
    table.add_column("Current %", justify="right")
    table.add_column("Drift %", justify="right")
    table.add_column("Drift $", justify="right")
    table.add_column("Action")
    table.add_column("Qty", justify="right")
    table.add_column("Notional", justify="right")

    qty_lookup = {t.symbol: t.quantity for t in (trades or [])}
    notional_lookup = {t.symbol: t.notional for t in (trades or [])}

    for d in plan:
        qty = qty_lookup.get(d.symbol, 0.0)
        notional = notional_lookup.get(d.symbol, 0.0)
        table.add_row(
            d.symbol,
            f"{d.target_wt_pct:.2f}",
            f"{d.current_wt_pct:.2f}",
            f"{d.drift_pct:.2f}",
            f"{d.drift_usd:.2f}",
            d.action,
            f"{qty:.2f}",
            f"{notional:.2f}",
        )

    # Rich will downgrade its output when the destination isn't a real
    # terminal (``isatty`` returns ``False``).  In the unit tests we render the
    # table to an in-memory ``StringIO`` which Rich interprets as a plain file
    # and therefore falls back to an ASCII only box drawing style and, more
    # problematically, drops the header text.  Force terminal mode so that the
    # exported table is stable and always uses the Unicode box characters the
    # tests expect.
    # ``Rich`` attempts to auto-detect terminal capabilities which can result
    # in reduced widths or ASCII only tables when rendering to an in-memory
    # ``StringIO`` buffer during testing.  Explicitly widen the virtual
    # terminal to ensure that column headers are never truncated regardless of
    # the executing environment.
    console = Console(
        file=StringIO(),
        record=True,
        force_terminal=True,
        width=120,
    )
    console.print(table)

    gross_buy = sum(t.notional for t in (trades or []) if t.action == "BUY")
    gross_sell = sum(t.notional for t in (trades or []) if t.action == "SELL")

    summary = Table(title="Batch Summary", show_header=False)
    summary.add_column("Metric")
    summary.add_column("Value", justify="right")
    summary.add_row("Gross Buy", f"{gross_buy:.2f}")
    summary.add_row("Gross Sell", f"{gross_sell:.2f}")
    summary.add_row("Pre Gross Exposure", f"{pre_gross_exposure:.2f}")
    summary.add_row("Pre Leverage", f"{pre_leverage:.2f}")
    summary.add_row("Post Gross Exposure", f"{post_gross_exposure:.2f}")
    summary.add_row("Post Leverage", f"{post_leverage:.2f}")

    console.print()
    console.print(summary)
    return console.export_text()


if __name__ == "__main__":  # pragma: no cover - convenience demo
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
    print(render(sample_plan, sample_trades, pre_exp, pre_lev, post_exp, post_lev))
