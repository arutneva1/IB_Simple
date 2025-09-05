"""Validate portfolio CSV files for IB_Simple."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .config_loader import ConfigError, load_config
from .portfolio_csv import PortfolioCSVError, load_portfolios, load_portfolios_map


async def main(path: str, *, config_path: str, validate_all: bool = False) -> None:
    """Validate portfolio CSVs printing ``OK`` on success.

    Parameters
    ----------
    path:
        Global portfolio CSV shared across accounts.
    config_path:
        Path to ``settings.ini``.
    validate_all:
        When ``True``, validate the global CSV plus any per-account
        overrides found in the configuration.
    """

    try:
        cfg = load_config(Path(config_path))
    except (ConfigError, OSError) as exc:
        print(exc)
        raise SystemExit(1)

    try:
        if validate_all:
            path_map = {
                acct: cfg.portfolio_paths.get(acct, Path(path))
                for acct in cfg.accounts.ids
            }
            await load_portfolios_map(
                path_map,
                host=cfg.ibkr.host,
                port=cfg.ibkr.port,
                client_id=cfg.ibkr.client_id,
            )
        else:
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
    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate the global CSV plus any per-account overrides",
    )
    args = parser.parse_args()
    asyncio.run(main(args.csv_path, config_path=args.config, validate_all=args.all))
