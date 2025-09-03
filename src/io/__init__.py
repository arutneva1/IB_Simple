"""IO utilities for IB_Simple.

This package exposes the configuration loader along with the dataclasses it
produces.  Importing from :mod:`src.io` gives convenient access to these
types without reaching into the underlying modules.
"""

from .config_loader import (
    IBKR,
    IO,
    AppConfig,
    ConfigError,
    Execution,
    Models,
    Pricing,
    Rebalance,
    load_config,
)
from .portfolio_csv import PortfolioCSVError, load_portfolios, validate_symbols
from .reporting import setup_logging, write_post_trade_report, write_pre_trade_report

__all__ = [
    "AppConfig",
    "ConfigError",
    "Execution",
    "IBKR",
    "IO",
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
]
