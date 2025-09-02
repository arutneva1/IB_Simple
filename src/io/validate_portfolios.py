"""Validate portfolio CSV files for IB_Simple."""

from __future__ import annotations

from pathlib import Path

from .portfolio_csv import PortfolioCSVError, load_portfolios


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
        print("Usage: python -m src.io.validate_portfolios <CSV_PATH>")
        raise SystemExit(1)
    main(sys.argv[1])
