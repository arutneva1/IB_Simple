"""IO utilities for IB_Simple.

This package exposes the configuration loader along with the dataclasses it
produces.  Importing from :mod:`src.io` gives convenient access to these
types without reaching into the underlying modules.
"""

from .config_loader import (
    IBKR,
    IO,
    Accounts,
    AppConfig,
    ConfigError,
    ConfirmMode,
    Execution,
    Models,
    Pricing,
    Rebalance,
    account_overrides,
    load_config,
)
from .portfolio_csv import PortfolioCSVError, load_portfolios, validate_symbols
from .reporting import (
    append_run_summary,
    setup_logging,
    write_post_trade_report,
    write_pre_trade_report,
)

__all__ = [
    "AppConfig",
    "Accounts",
    "ConfirmMode",
    "ConfigError",
    "Execution",
    "IBKR",
    "IO",
    "account_overrides",
    "Models",
    "Pricing",
    "Rebalance",
    "load_config",
    "PortfolioCSVError",
    "load_portfolios",
    "validate_symbols",
    "setup_logging",
    "write_pre_trade_report",
    "write_post_trade_report",
    "append_run_summary",
]
