"""Portfolio target weight calculations.

This module combines multiple model portfolios into a single set of target
weights based on a user supplied mix.  The mix determines the overall
contribution of each model to the final allocation.
"""

from __future__ import annotations

import argparse
from math import isclose
from pathlib import Path

from ..io import load_config, load_portfolios
from ..io.config_loader import Models


class TargetError(ValueError):
    """Raised when generated target weights are invalid."""


def build_targets(
    models: dict[str, dict[str, float]],
    mix: Models,
) -> dict[str, float]:
    """Combine model portfolios according to ``mix``.

    Parameters
    ----------
    models:
        Mapping of symbols to per-model weights expressed in percent.  Each
        inner mapping may omit some model keys; missing weights are treated as
        ``0.0``.
    mix:
        Relative weighting of the individual models.  The ``smurf``,
        ``badass`` and ``gltr`` fields should sum to ``1.0``.

    Returns
    -------
    dict[str, float]
        Final target weights in percent for each symbol.  ``CASH`` is included
        when present in the input ``models`` mapping.

    Raises
    ------
    TargetError
        If the resulting weights do not sum to approximately ``100`` percent.
    """

    targets: dict[str, float] = {}
    for symbol, wt in models.items():
        weight = (
            mix.smurf * wt.get("smurf", 0.0)
            + mix.badass * wt.get("badass", 0.0)
            + mix.gltr * wt.get("gltr", 0.0)
        )
        targets[symbol] = weight

    total = sum(targets.values())
    if not isclose(total, 100.0, abs_tol=0.01):
        raise TargetError(f"target weights sum to {total:.2f}%, expected 100%")

    return targets


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    ns = parser.parse_args(argv)

    cfg = load_config(ns.config)
    models = load_portfolios(
        ns.csv, host=cfg.ibkr.host, port=cfg.ibkr.port, client_id=cfg.ibkr.client_id
    )
    targets = build_targets(models, cfg.models)
    for symbol, pct in sorted(targets.items()):
        print(f"{symbol} {pct:.1f}%")


__all__ = ["TargetError", "build_targets"]


if __name__ == "__main__":
    main()
