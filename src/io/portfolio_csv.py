"""Portfolio CSV loader for IB_Simple."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict


class PortfolioCSVError(Exception):
    """Raised when portfolio CSV validation fails."""


def _parse_percent(value: str, *, symbol: str, model: str) -> float:
    """Parse a percentage string into a float between 0 and 100."""

    text = value.strip()
    if not text:
        return 0.0
    if text.endswith("%"):
        text = text[:-1]
    try:
        pct = float(text)
    except ValueError as exc:
        raise PortfolioCSVError(
            f"{symbol}: invalid percentage for {model}: {value!r}"
        ) from exc
    if pct < 0 or pct > 100:
        raise PortfolioCSVError(f"{symbol}: percent out of range for {model}: {pct}")
    return pct


def load_portfolios(path: Path) -> dict[str, dict[str, float]]:
    """Load portfolio model weights from ``path``.

    Parameters
    ----------
    path:
        CSV file containing columns ``ETF, SMURF, BADASS, GLTR`` with
        percentage strings.
    """

    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise PortfolioCSVError("Missing header")
        expected = ["ETF", "SMURF", "BADASS", "GLTR"]
        if len(fieldnames) != len(set(fieldnames)):
            dupes = [n for n in fieldnames if fieldnames.count(n) > 1]
            raise PortfolioCSVError(f"Duplicate columns: {', '.join(dupes)}")
        if set(fieldnames) != set(expected):
            extra = set(fieldnames) - set(expected)
            missing = set(expected) - set(fieldnames)
            parts = []
            if extra:
                parts.append(f"Unknown columns: {', '.join(sorted(extra))}")
            if missing:
                parts.append(f"Missing columns: {', '.join(sorted(missing))}")
            raise PortfolioCSVError("; ".join(parts))

        portfolios: Dict[str, Dict[str, float]] = {}
        for row in reader:
            symbol = (row.get("ETF") or "").strip()
            if not symbol:
                raise PortfolioCSVError("Blank ETF symbol")
            if symbol in portfolios:
                raise PortfolioCSVError(f"Duplicate ETF symbol: {symbol}")
            weights: Dict[str, float] = {}
            for model in ("SMURF", "BADASS", "GLTR"):
                raw = row.get(model) or ""
                weight = _parse_percent(raw, symbol=symbol, model=model)
                weights[model.lower()] = weight
            portfolios[symbol] = weights
    return portfolios


def main(path: str) -> None:
    """Validate and load ``path`` printing ``OK`` on success."""

    try:
        load_portfolios(Path(path))
    except PortfolioCSVError as exc:
        print(exc)
        raise SystemExit(1)
    print("OK")


if __name__ == "__main__":  # pragma: no cover - CLI utility
    import sys

    if len(sys.argv) != 2:
        print("Usage: python -m src.io.portfolio_csv <CSV_PATH>")
        raise SystemExit(1)
    main(sys.argv[1])
