"""Configuration loader for IB_Simple.

This module parses ``settings.ini`` files into structured dataclasses.
"""

from __future__ import annotations

import logging
from configparser import ConfigParser, NoOptionError, NoSectionError
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Mapping


class ConfigError(Exception):
    """Raised when configuration loading or validation fails."""


class ConfirmMode(Enum):
    """Confirmation prompt behavior."""

    PER_ACCOUNT = "per_account"
    GLOBAL = "global"


@dataclass
class IBKR:
    """Settings for Interactive Brokers connection."""

    host: str
    port: int
    client_id: int
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
    trading_hours: str
    max_passes: int


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
    wait_before_fallback: float


@dataclass
class IO:
    """Input/output options."""

    report_dir: str
    log_level: str


@dataclass
class AccountOverride:
    """Per-account override values for rebalance settings."""

    allow_fractional: bool | None = None
    min_order_usd: int | None = None
    cash_buffer_type: str | None = None
    cash_buffer_pct: float | None = None
    cash_buffer_abs: float | None = None
    extra: Dict[str, str] = field(default_factory=dict)


@dataclass
class Accounts:
    """Configuration for multiple trading accounts."""

    ids: list[str]
    confirm_mode: ConfirmMode
    pacing_sec: float = 0.0
    parallel: bool = False


@dataclass
class AppConfig:
    """Top level application configuration."""

    ibkr: IBKR
    models: Models
    rebalance: Rebalance
    pricing: Pricing
    execution: Execution
    io: IO
    accounts: Accounts
    account_overrides: Dict[str, AccountOverride] = field(default_factory=dict)
    portfolio_paths: Dict[str, Path] = field(default_factory=dict)


TOLERANCE = 0.001


def _load_section(cp: ConfigParser, section: str) -> Dict[str, str]:
    try:
        return dict(cp.items(section))
    except NoSectionError as exc:
        raise ConfigError(f"Missing section [{section}]") from exc


def _parse_account_override(items: Mapping[str, str]) -> AccountOverride:
    """Convert raw key/value pairs into an :class:`AccountOverride`."""

    ov = AccountOverride()
    for key, val in items.items():
        lk = key.lower()
        if lk == "allow_fractional":
            ov.allow_fractional = val.lower() in {"1", "true", "yes", "on"}
        elif lk == "min_order_usd":
            try:
                ov.min_order_usd = int(val)
            except ValueError as exc:
                raise ConfigError(
                    f"[account] invalid int for min_order_usd: {val}"
                ) from exc
        elif lk == "cash_buffer_type":
            ov.cash_buffer_type = val.lower()
        elif lk == "cash_buffer_pct":
            try:
                ov.cash_buffer_pct = float(val)
            except ValueError as exc:
                raise ConfigError(
                    f"[account] invalid float for cash_buffer_pct: {val}"
                ) from exc
        elif lk == "cash_buffer_abs":
            try:
                ov.cash_buffer_abs = float(val)
            except ValueError as exc:
                raise ConfigError(
                    f"[account] invalid float for cash_buffer_abs: {val}"
                ) from exc
        else:
            ov.extra[key] = val
    if ov.extra:
        logging.warning(
            "Ignoring unknown account override keys: %s",
            ", ".join(sorted(ov.extra.keys())),
        )
    return ov


def merge_account_overrides(cfg: Any, account_id: str) -> Any:
    """Return a copy of ``cfg`` with overrides for ``account_id`` applied."""

    norm_id = account_id.strip().upper()
    overrides = getattr(cfg, "account_overrides", {}).get(norm_id)
    if not overrides:
        return cfg

    reb_updates = {}
    for field_name in (
        "allow_fractional",
        "min_order_usd",
        "cash_buffer_type",
        "cash_buffer_pct",
        "cash_buffer_abs",
    ):
        val = getattr(overrides, field_name)
        if val is not None:
            reb_updates[field_name] = val

    if not reb_updates:
        return cfg

    reb_src = getattr(cfg, "rebalance", None)
    if reb_src is None:
        return cfg
    try:
        reb = replace(reb_src, **reb_updates)
    except TypeError:
        reb = SimpleNamespace(**{**getattr(reb_src, "__dict__", {}), **reb_updates})
    try:
        return replace(cfg, rebalance=reb)
    except TypeError:
        cfg_dict = {**getattr(cfg, "__dict__", {})}
        cfg_dict["rebalance"] = reb
        return SimpleNamespace(**cfg_dict)


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
        read_only = cp.getboolean("ibkr", "read_only")
    except (NoSectionError, NoOptionError, ValueError) as exc:
        raise ConfigError(f"[ibkr] {exc}") from exc
    if cp.has_option("ibkr", "account_id"):
        raise ConfigError(
            "[ibkr] account_id is no longer supported; use [accounts] ids"
        )
    if port <= 0:
        raise ConfigError("[ibkr] port must be positive")
    if client_id < 0:
        raise ConfigError("[ibkr] client_id must be non-negative")

    if not cp.has_section("accounts"):
        raise ConfigError("Missing section [accounts]")
    try:
        raw_ids = cp.get("accounts", "ids")
    except NoOptionError as exc:
        raise ConfigError("[accounts] missing key: ids") from exc
    ids: list[str] = []
    seen: set[str] = set()
    for s in raw_ids.split(","):
        s = s.strip().upper()
        if s and s not in seen:
            ids.append(s)
            seen.add(s)
    if not ids:
        raise ConfigError("[accounts] ids must be non-empty")
    confirm_mode_str = (
        cp.get(
            "accounts",
            "confirm_mode",
            fallback="per_account",
        )
        .strip()
        .lower()
    )
    try:
        confirm_mode = ConfirmMode(confirm_mode_str)
    except ValueError as exc:
        raise ConfigError(
            "[accounts] confirm_mode must be 'per_account' or 'global'"
        ) from exc
    try:
        pacing_sec = cp.getfloat("accounts", "pacing_sec", fallback=0.0)
    except ValueError as exc:
        raise ConfigError("[accounts] pacing_sec must be a float") from exc
    if pacing_sec < 0:
        raise ConfigError("[accounts] pacing_sec must be >= 0")
    try:
        parallel = cp.getboolean("accounts", "parallel", fallback=False)
    except ValueError as exc:
        raise ConfigError("[accounts] parallel must be a boolean") from exc
    accounts = Accounts(
        ids=ids,
        confirm_mode=confirm_mode,
        pacing_sec=pacing_sec,
        parallel=parallel,
    )

    ibkr = IBKR(
        host=host,
        port=port,
        client_id=client_id,
        read_only=read_only,
    )

    account_overrides: Dict[str, AccountOverride] = {}
    for section in cp.sections():
        if section.startswith("account:"):
            acc_id = section.split("account:", 1)[1].strip().upper()
            items = dict(cp.items(section))
            account_overrides[acc_id] = _parse_account_override(items)

    portfolio_paths: Dict[str, Path] = {}
    for section in cp.sections():
        if section.startswith("portfolio:"):
            acc_id = section.split("portfolio:", 1)[1].strip().upper()
            try:
                portfolio_paths[acc_id] = Path(cp.get(section, "path"))
            except NoOptionError as exc:
                raise ConfigError(f"[{section}] missing key: path") from exc

    unknown_accounts = sorted(set(portfolio_paths) - set(accounts.ids))
    if unknown_accounts:
        raise ConfigError(
            "[portfolio] unknown account ids: " + ", ".join(unknown_accounts)
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
        trading_hours = cp.get("rebalance", "trading_hours").strip().lower()
        max_passes = cp.getint("rebalance", "max_passes", fallback=1)
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
    if trading_hours not in {"rth", "eth"}:
        raise ConfigError("[rebalance] trading_hours must be 'rth' or 'eth'")
    if max_passes <= 0:
        raise ConfigError("[rebalance] max_passes must be >= 1")
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
        trading_hours=trading_hours,
        max_passes=max_passes,
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
            wait_before_fallback=cp.getfloat(
                "execution", "wait_before_fallback", fallback=300.0
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
        accounts=accounts,
        account_overrides=account_overrides,
        portfolio_paths=portfolio_paths,
    )


if __name__ == "__main__":  # pragma: no cover - CLI utility
    import sys

    try:
        cfg = load_config(Path(sys.argv[1]))
    except (IndexError, ConfigError) as exc:  # missing path or config error
        print(exc)
        raise SystemExit(1)
    print("OK")
