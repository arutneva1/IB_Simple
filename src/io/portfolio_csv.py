"""Portfolio CSV loader for IB_Simple."""

from __future__ import annotations

import copy
import csv
from pathlib import Path
from typing import Dict, Iterable, Mapping

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


async def validate_symbols(
    symbols: Iterable[str], *, host: str, port: int, client_id: int
) -> None:
    """Ensure ``symbols`` are valid USD-denominated ETFs.

    Parameters
    ----------
    symbols:
        Iterable of ticker symbols to validate.
    host, port, client_id:
        Connection parameters for Interactive Brokers.

    Raises
    ------
    PortfolioCSVError
        If a symbol is unknown or does not represent a USD ETF.
    """

    symbols_to_check = [s for s in symbols if s != "CASH"]
    if not symbols_to_check:
        return

    ib = IB()
    try:
        try:
            await ib.connectAsync(host, port, clientId=client_id)
            for symbol in symbols_to_check:
                details = await ib.reqContractDetailsAsync(
                    Stock(symbol=symbol, currency="USD")
                )
                if not details:
                    raise PortfolioCSVError(f"Unknown ETF symbol: {symbol}")
                cd = details[0]
                contract = cd.contract
                if (
                    contract is None
                    or contract.currency != "USD"
                    or cd.stockType != "ETF"
                ):
                    raise PortfolioCSVError(f"{symbol}: not a USD-denominated ETF")
        except OSError as exc:  # pragma: no cover - network failure
            # Limit this handler to connection-related issues so that
            # PortfolioCSVError raised above (e.g., unknown symbols) is not
            # swallowed and users can see the actual validation problem.
            raise PortfolioCSVError(f"IB connection failed: {exc}") from exc
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


async def load_portfolios(
    path: Path, *, host: str, port: int, client_id: int
) -> dict[str, dict[str, float]]:
    """Load portfolio model weights from ``path``.

    Parameters
    ----------
    path:
        CSV file containing columns ``ETF, SMURF, BADASS, GLTR`` with
        percentage strings.
    """

    portfolios, _ = _parse_csv(path, ["ETF", "SMURF", "BADASS", "GLTR"])
    await validate_symbols(portfolios.keys(), host=host, port=port, client_id=client_id)
    _validate_totals(portfolios)
    return portfolios


def _parse_csv(
    path: Path, expected: list[str] | None = None
) -> tuple[dict[str, dict[str, float]], list[str]]:
    with path.open(newline="") as fh:
        filtered = (
            line for line in fh if line.strip() and not line.lstrip().startswith("#")
        )
        reader = csv.DictReader(filtered)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise PortfolioCSVError("Missing header")
        field_list = list(fieldnames)
        if len(field_list) != len(set(field_list)):
            dupes = {n for n in field_list if field_list.count(n) > 1}
            raise PortfolioCSVError(f"Duplicate columns: {', '.join(sorted(dupes))}")
        exp = expected or field_list
        if set(field_list) != set(exp):
            extra = set(field_list) - set(exp)
            missing = set(exp) - set(field_list)
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
            for model in field_list[1:]:
                raw = row.get(model) or ""
                weight = _parse_percent(raw, symbol=symbol, model=model)
                weights[model.lower()] = weight
            portfolios[symbol] = weights
    return portfolios, field_list


def _validate_totals(portfolios: Dict[str, Dict[str, float]]) -> None:
    models = next(iter(portfolios.values())).keys() if portfolios else []
    totals = {m: 0.0 for m in models}
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


async def load_portfolios_map(
    paths: Mapping[str, Path],
    *,
    host: str,
    port: int,
    client_id: int,
    expected: list[str] | None = None,
) -> dict[str, dict[str, dict[str, float]]]:
    expected = expected or ["ETF", "SMURF", "BADASS", "GLTR"]
    cache: Dict[Path, dict[str, dict[str, float]]] = {}
    result: Dict[str, dict[str, dict[str, float]]] = {}
    symbols: set[str] = set()
    for account, p in paths.items():
        # Resolve the path so that different references (relative vs. absolute)
        # to the same file map to a single cache entry.
        path = Path(p).resolve()
        data = cache.get(path)
        if data is None:
            portfolios, expected = _parse_csv(path, expected)
            _validate_totals(portfolios)
            cache[path] = portfolios
            symbols.update(portfolios.keys())
        result[account] = copy.deepcopy(cache[path])
    await validate_symbols(symbols, host=host, port=port, client_id=client_id)
    return result
