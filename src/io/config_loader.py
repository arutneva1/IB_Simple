"""Configuration loader for IB_Simple.

This module parses ``settings.ini`` files into structured dataclasses.
"""

from __future__ import annotations

from configparser import ConfigParser, NoOptionError, NoSectionError
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""


@dataclass
class IBKR:
    """Settings for Interactive Brokers connection."""

    host: str
    port: int
    client_id: int
    account_id: str
    read_only: bool


@dataclass
class Models:
    """Model weightings that must sum to 1.0."""

    smurf: float
    badass: float
    gltr: float


@dataclass
class Rebalance:
    """Rebalancing configuration options."""

    trigger_mode: str
    per_holding_band_bps: int
    portfolio_total_band_bps: int
    min_order_usd: int
    cash_buffer_type: str
    cash_buffer_pct: float | None  # decimal fraction (e.g., 0.01 = 1%)
    cash_buffer_abs: float | None
    allow_fractional: bool
    max_leverage: float
    maintenance_buffer_pct: float  # decimal fraction (e.g., 0.10 = 10%)
    prefer_rth: bool


@dataclass
class Pricing:
    """Pricing configuration."""

    price_source: str
    fallback_to_snapshot: bool


@dataclass
class Execution:
    """Order execution preferences."""

    order_type: str
    algo_preference: str
    fallback_plain_market: bool
    batch_orders: bool
    commission_report_timeout: float


@dataclass
class IO:
    """Input/output options."""

    report_dir: str
    log_level: str


@dataclass
class AppConfig:
    """Top level application configuration."""

    ibkr: IBKR
    models: Models
    rebalance: Rebalance
    pricing: Pricing
    execution: Execution
    io: IO


TOLERANCE = 0.001


def _load_section(cp: ConfigParser, section: str) -> Dict[str, str]:
    try:
        return dict(cp.items(section))
    except NoSectionError as exc:
        raise ConfigError(f"Missing section [{section}]") from exc


def load_config(path: Path) -> AppConfig:
    """Load configuration from an INI file."""

    cp = ConfigParser()
    if not cp.read(path):
        raise ConfigError(f"Cannot read config: {path}")

    # [ibkr]
    try:
        host = cp.get("ibkr", "host")
        port = cp.getint("ibkr", "port")
        client_id = cp.getint("ibkr", "client_id")
        account_id = cp.get("ibkr", "account_id")
        read_only = cp.getboolean("ibkr", "read_only")
    except (NoSectionError, NoOptionError, ValueError) as exc:
        raise ConfigError(f"[ibkr] {exc}") from exc
    if port <= 0:
        raise ConfigError("[ibkr] port must be positive")
    if client_id < 0:
        raise ConfigError("[ibkr] client_id must be non-negative")
    ibkr = IBKR(
        host=host,
        port=port,
        client_id=client_id,
        account_id=account_id,
        read_only=read_only,
    )

    # [models]
    data = _load_section(cp, "models")
    required_models = ["smurf", "badass", "gltr"]
    try:
        weights = {k: float(data[k]) for k in required_models}
    except KeyError as exc:
        raise ConfigError(f"[models] missing key: {exc.args[0]}") from exc
    except ValueError as exc:
        raise ConfigError(f"[models] invalid float: {exc}") from exc
    if any(v < 0 for v in weights.values()):
        raise ConfigError("[models] weights must be non-negative")
    total = sum(weights.values())
    if abs(total - 1.0) > TOLERANCE:
        raise ConfigError(
            f"[models] weights must sum to 1.0 (±{TOLERANCE}); got {total:.4f}"
        )
    models = Models(**weights)  # type: ignore[arg-type]

    # [rebalance]
    try:
        trigger_mode = cp.get("rebalance", "trigger_mode")
        per_holding_band_bps = cp.getint("rebalance", "per_holding_band_bps")
        portfolio_total_band_bps = cp.getint("rebalance", "portfolio_total_band_bps")
        min_order_usd = cp.getint("rebalance", "min_order_usd")
        cash_buffer_type = cp.get(
            "rebalance", "cash_buffer_type", fallback="abs"
        ).lower()
        allow_fractional = cp.getboolean("rebalance", "allow_fractional")
        max_leverage = cp.getfloat("rebalance", "max_leverage")
        maintenance_buffer_pct = cp.getfloat("rebalance", "maintenance_buffer_pct")
        prefer_rth = cp.getboolean("rebalance", "prefer_rth")
    except (NoSectionError, NoOptionError, ValueError) as exc:
        raise ConfigError(f"[rebalance] {exc}") from exc
    if per_holding_band_bps < 0:
        raise ConfigError("[rebalance] per_holding_band_bps must be >= 0")
    if portfolio_total_band_bps < 0:
        raise ConfigError("[rebalance] portfolio_total_band_bps must be >= 0")
    if min_order_usd <= 0:
        raise ConfigError("[rebalance] min_order_usd must be positive")
    cash_buffer_pct = None
    cash_buffer_abs = None
    if cash_buffer_type == "pct":
        try:
            cash_buffer_pct = cp.getfloat("rebalance", "cash_buffer_pct")
        except (NoOptionError, ValueError) as exc:
            raise ConfigError(
                "[rebalance] cash_buffer_pct is required when cash_buffer_type=pct"
            ) from exc
        if not 0 <= cash_buffer_pct <= 1:
            raise ConfigError("[rebalance] cash_buffer_pct must be between 0 and 1")
    elif cash_buffer_type == "abs":
        try:
            cash_buffer_abs = cp.getfloat("rebalance", "cash_buffer_abs")
        except (NoOptionError, ValueError) as exc:
            raise ConfigError(
                "[rebalance] cash_buffer_abs is required when cash_buffer_type=abs"
            ) from exc
        if cash_buffer_abs < 0:
            raise ConfigError("[rebalance] cash_buffer_abs must be >= 0")
    else:
        raise ConfigError("[rebalance] cash_buffer_type must be 'pct' or 'abs'")
    if max_leverage <= 0:
        raise ConfigError("[rebalance] max_leverage must be positive")
    if not 0 <= maintenance_buffer_pct <= 1:
        raise ConfigError("[rebalance] maintenance_buffer_pct must be between 0 and 1")
    rebalance = Rebalance(
        trigger_mode=trigger_mode,
        per_holding_band_bps=per_holding_band_bps,
        portfolio_total_band_bps=portfolio_total_band_bps,
        min_order_usd=min_order_usd,
        cash_buffer_type=cash_buffer_type,
        cash_buffer_pct=cash_buffer_pct,
        cash_buffer_abs=cash_buffer_abs,
        allow_fractional=allow_fractional,
        max_leverage=max_leverage,
        maintenance_buffer_pct=maintenance_buffer_pct,
        prefer_rth=prefer_rth,
    )

    # [pricing]
    try:
        pricing = Pricing(
            price_source=cp.get("pricing", "price_source"),
            fallback_to_snapshot=cp.getboolean("pricing", "fallback_to_snapshot"),
        )
    except (NoSectionError, NoOptionError, ValueError) as exc:
        raise ConfigError(f"[pricing] {exc}") from exc

    # [execution]
    try:
        execution = Execution(
            order_type=cp.get("execution", "order_type"),
            algo_preference=cp.get("execution", "algo_preference"),
            fallback_plain_market=cp.getboolean("execution", "fallback_plain_market"),
            batch_orders=cp.getboolean("execution", "batch_orders"),
            commission_report_timeout=cp.getfloat(
                "execution", "commission_report_timeout", fallback=5.0
            ),
        )
    except (NoSectionError, NoOptionError, ValueError) as exc:
        raise ConfigError(f"[execution] {exc}") from exc

    # [io]
    try:
        io_cfg = IO(
            report_dir=cp.get("io", "report_dir"),
            log_level=cp.get("io", "log_level"),
        )
    except (NoSectionError, NoOptionError, ValueError) as exc:
        raise ConfigError(f"[io] {exc}") from exc

    return AppConfig(
        ibkr=ibkr,
        models=models,
        rebalance=rebalance,
        pricing=pricing,
        execution=execution,
        io=io_cfg,
    )


if __name__ == "__main__":  # pragma: no cover - CLI utility
    import sys

    try:
        cfg = load_config(Path(sys.argv[1]))
    except (IndexError, ConfigError) as exc:  # missing path or config error
        print(exc)
        raise SystemExit(1)
    print("OK")
