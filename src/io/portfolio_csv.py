"""Portfolio CSV loader for IB_Simple."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Iterable

from ib_async import IB
from ib_async.contract import Stock


class PortfolioCSVError(Exception):
    """Raised when portfolio CSV validation fails."""


def _parse_percent(value: str, *, symbol: str, model: str) -> float:
    """Parse a percentage string into a float."""

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

    if symbol == "CASH":
        limit_low = -100.0
    else:
        limit_low = 0.0
    if pct < limit_low or pct > 100.0:
        raise PortfolioCSVError(f"{symbol}: percent out of range for {model}: {pct}")
    return pct


def validate_symbols(symbols: Iterable[str]) -> None:
    """Ensure ``symbols`` are valid USD-denominated ETFs.

    Parameters
    ----------
    symbols:
        Iterable of ticker symbols to validate.

    Raises
    ------
    PortfolioCSVError
        If a symbol is unknown or does not represent a USD ETF.
    """

    ib = IB()
    for symbol in symbols:
        if symbol == "CASH":
            continue
        details = ib.reqContractDetails(Stock(symbol=symbol, currency="USD"))
        if not details:
            raise PortfolioCSVError(f"Unknown ETF symbol: {symbol}")
        cd = details[0]
        contract = cd.contract
        if contract is None or contract.currency != "USD" or cd.stockType != "ETF":
            raise PortfolioCSVError(f"{symbol}: not a USD-denominated ETF")


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

    validate_symbols(portfolios.keys())

    totals = {"smurf": 0.0, "badass": 0.0, "gltr": 0.0}
    for symbol, weights in portfolios.items():
        if symbol == "CASH":
            continue
        for model, weight in weights.items():
            totals[model] += weight

    cash_weights = portfolios.get("CASH")
    for model, total in totals.items():
        if cash_weights is None:
            if abs(total - 100.0) > 0.01:
                raise PortfolioCSVError(
                    f"{model.upper()}: totals {total:.2f}% do not sum to 100%"
                )
        else:
            cash = cash_weights[model]
            combined = total + cash
            if abs(combined - 100.0) > 0.01:
                raise PortfolioCSVError(
                    f"{model.upper()}: assets {total:.2f}% + CASH {cash:.2f}% = "
                    f"{combined:.2f}%, expected 100%"
                )
    return portfolios
