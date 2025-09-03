"""Validate portfolio CSV files for IB_Simple."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .config_loader import ConfigError, load_config
from .portfolio_csv import PortfolioCSVError, load_portfolios


async def main(path: str, *, config_path: str) -> None:
    """Validate and load ``path`` printing ``OK`` on success."""

    try:
        cfg = load_config(Path(config_path))
    except (ConfigError, OSError) as exc:
        print(exc)
        raise SystemExit(1)

    try:
        await load_portfolios(
            Path(path),
            host=cfg.ibkr.host,
            port=cfg.ibkr.port,
            client_id=cfg.ibkr.client_id,
        )
    except PortfolioCSVError as exc:
        print(exc)
        raise SystemExit(1)
    print("OK")


if __name__ == "__main__":  # pragma: no cover - CLI utility
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="Portfolio CSV to validate")
    parser.add_argument("--config", required=True, help="Path to settings.ini")
    args = parser.parse_args()
    asyncio.run(main(args.csv_path, config_path=args.config))
