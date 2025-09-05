"""IO utilities for IB_Simple.

This package exposes the configuration loader along with the dataclasses it
produces.  Importing from :mod:`src.io` gives convenient access to these
types without reaching into the underlying modules.
"""

from .config_loader import (
    IBKR,
    IO,
    AccountOverride,
    Accounts,
    AppConfig,
    ConfigError,
    ConfirmMode,
    Execution,
    Models,
    Pricing,
    Rebalance,
    load_config,
    merge_account_overrides,
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
    "AccountOverride",
    "Models",
    "Pricing",
    "Rebalance",
    "load_config",
    "merge_account_overrides",
    "PortfolioCSVError",
    "load_portfolios",
    "validate_symbols",
    "setup_logging",
    "write_pre_trade_report",
    "write_post_trade_report",
    "append_run_summary",
]
