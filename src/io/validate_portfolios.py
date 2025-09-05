"""Validate portfolio CSV files for IB_Simple."""

from __future__ import annotations

import asyncio
from pathlib import Path

from .config_loader import ConfigError, load_config
from .portfolio_csv import PortfolioCSVError, load_portfolios, load_portfolios_map


async def main(
    path: str | None = None, *, config_path: str, validate_all: bool = False
) -> None:
    """Validate portfolio CSVs printing ``OK`` on success.

    Parameters
    ----------
    path:
        Global portfolio CSV shared across accounts. Required unless every
        account has a dedicated portfolio CSV configured.
    config_path:
        Path to ``settings.ini``.
    validate_all:
        When ``True``, validate the global CSV plus any per-account overrides
        found in the configuration.
    """

    try:
        cfg = load_config(Path(config_path))
    except (ConfigError, OSError) as exc:
        print(exc)
        raise SystemExit(1)

    cfg_dir = Path(config_path).resolve().parent
    global_path: Path | None = None
    if path is not None:
        p = Path(path)
        if not p.is_absolute():
            p = (cfg_dir / p).resolve()
        global_path = p
    else:
        accounts_path = cfg.accounts.path
        if accounts_path is not None:
            p = accounts_path
            if not p.is_absolute():
                p = (cfg_dir / p).resolve()
            global_path = p

    missing = [acct for acct in cfg.accounts.ids if acct not in cfg.portfolio_paths]
    all_have_paths = not missing

    try:
        if validate_all or all_have_paths:
            if not all_have_paths:
                if global_path is None:
                    missing_ids = ", ".join(missing)
                    print(
                        "CSV path required for accounts without overrides: "
                        f"{missing_ids}"
                    )
                    raise SystemExit(1)
                path_map = {
                    acct: cfg.portfolio_paths.get(acct, global_path)
                    for acct in cfg.accounts.ids
                }
            else:
                path_map = {
                    acct: cfg.portfolio_paths[acct] for acct in cfg.accounts.ids
                }
            await load_portfolios_map(
                path_map,
                host=cfg.ibkr.host,
                port=cfg.ibkr.port,
                client_id=cfg.ibkr.client_id,
            )
        else:
            if global_path is None:
                print("CSV path required")
                raise SystemExit(1)
            await load_portfolios(
                global_path,
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
    parser.add_argument(
        "csv_path",
        nargs="?",
        help=(
            "Global portfolio CSV shared across accounts. Required unless every "
            "account has a dedicated portfolio CSV configured."
        ),
    )
    parser.add_argument("--config", required=True, help="Path to settings.ini")
    parser.add_argument(
        "--all",
        action="store_true",
        help=(
            "Validate the global CSV plus any per-account overrides. When every "
            "account has its own file, only those files are validated."
        ),
    )
    args = parser.parse_args()
    asyncio.run(main(args.csv_path, config_path=args.config, validate_all=args.all))
