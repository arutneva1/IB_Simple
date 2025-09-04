import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.io.config_loader import (
    IBKR,
    IO,
    Accounts,
    AppConfig,
    ConfigError,
    Execution,
    Models,
    Pricing,
    Rebalance,
    account_overrides,
    load_config,
)

VALID_CONFIG = """\
[ibkr]
host = 127.0.0.1
port = 4002
client_id = 42
account_id = DUA071544
read_only = true

[models]
smurf = 0.50
badass = 0.30
gltr = 0.20

[rebalance]
trigger_mode = per_holding
per_holding_band_bps = 50
portfolio_total_band_bps = 100
min_order_usd = 500
cash_buffer_type = pct
cash_buffer_pct = 0.01
cash_buffer_abs = 0
allow_fractional = false
max_leverage = 1.50
maintenance_buffer_pct = 0.10
trading_hours = rth

[pricing]
price_source = last
fallback_to_snapshot = true

[execution]
order_type = market
algo_preference = adaptive
fallback_plain_market = true
batch_orders = true
commission_report_timeout = 5.0

[io]
report_dir = reports
log_level = INFO
"""


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.ini"
    path.write_text(VALID_CONFIG)
    return path


def test_load_valid_config(config_file: Path) -> None:
    cfg = load_config(config_file)
    expected = AppConfig(
        ibkr=IBKR(
            host="127.0.0.1",
            port=4002,
            client_id=42,
            account_id="DUA071544",
            read_only=True,
        ),
        models=Models(smurf=0.50, badass=0.30, gltr=0.20),
        rebalance=Rebalance(
            trigger_mode="per_holding",
            per_holding_band_bps=50,
            portfolio_total_band_bps=100,
            min_order_usd=500,
            cash_buffer_type="pct",
            cash_buffer_pct=0.01,
            cash_buffer_abs=None,
            allow_fractional=False,
            max_leverage=1.50,
            maintenance_buffer_pct=0.10,
            trading_hours="rth",
        ),
        pricing=Pricing(price_source="last", fallback_to_snapshot=True),
        execution=Execution(
            order_type="market",
            algo_preference="adaptive",
            fallback_plain_market=True,
            batch_orders=True,
            commission_report_timeout=5.0,
        ),
        io=IO(report_dir="reports", log_level="INFO"),
        accounts=None,
    )
    assert cfg == expected


def test_missing_section(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "\n[pricing]\nprice_source = last\nfallback_to_snapshot = true\n\n",
        "\n",
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_invalid_trading_hours(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "trading_hours = rth", "trading_hours = lunar"
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_accounts_section_and_overrides(tmp_path: Path) -> None:
    content = (
        VALID_CONFIG
        + """\

[accounts]
ids = ACC1, ACC2
confirm_mode = global

[account:ACC1]
foo = bar

[account:ACC2]
baz = qux
"""
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.accounts == Accounts(
        ids=["ACC1", "ACC2"], confirm_mode="global", pacing_sec=0.0
    )
    assert account_overrides == {"ACC1": {"foo": "bar"}, "ACC2": {"baz": "qux"}}


def test_accounts_default_confirm_mode(tmp_path: Path) -> None:
    content = (
        VALID_CONFIG
        + """\

[accounts]
ids = ONLY
"""
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.accounts == Accounts(
        ids=["ONLY"], confirm_mode="per_account", pacing_sec=0.0
    )


def test_accounts_invalid_confirm_mode(tmp_path: Path) -> None:
    content = (
        VALID_CONFIG
        + """\

[accounts]
ids = A1
confirm_mode = per_order
"""
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_accounts_ids_dedup_and_precedence(tmp_path: Path) -> None:
    content = (
        VALID_CONFIG.replace("account_id = DUA071544", "account_id = SHOULD_IGNORE")
        + """\

[accounts]
ids = ACC1, ACC2, ACC1 , ACC3
"""
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.accounts == Accounts(
        ids=["ACC1", "ACC2", "ACC3"], confirm_mode="per_account", pacing_sec=0.0
    )
    assert cfg.ibkr.account_id == "ACC1"
    # Existing fields remain unchanged
    assert cfg.ibkr.host == "127.0.0.1"
    assert cfg.models.gltr == 0.20
    assert cfg.pricing.price_source == "last"


def test_accounts_without_ibkr_account_id(tmp_path: Path) -> None:
    content = (
        VALID_CONFIG.replace("account_id = DUA071544\n", "")
        + """\

[accounts]
ids = ACC1, ACC2
"""
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.ibkr.account_id == "ACC1"


def test_missing_key(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace("host = 127.0.0.1\n", "")
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_non_numeric_port(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace("port = 4002", "port = not_a_number")
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_negative_per_holding_band_bps(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "per_holding_band_bps = 50", "per_holding_band_bps = -5"
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_cash_buffer_pct_out_of_range(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace("cash_buffer_pct = 0.01", "cash_buffer_pct = 1.5")
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_cash_buffer_pct_negative(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace("cash_buffer_pct = 0.01", "cash_buffer_pct = -0.2")
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_cash_buffer_abs_valid(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "cash_buffer_type = pct\ncash_buffer_pct = 0.01\ncash_buffer_abs = 0",
        "cash_buffer_type = abs\ncash_buffer_abs = 100",
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.rebalance.cash_buffer_type == "abs"
    assert cfg.rebalance.cash_buffer_abs == 100
    assert cfg.rebalance.cash_buffer_pct is None


def test_cash_buffer_abs_missing(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "cash_buffer_type = pct\ncash_buffer_pct = 0.01\ncash_buffer_abs = 0",
        "cash_buffer_type = abs",
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_cash_buffer_abs_negative(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "cash_buffer_type = pct\ncash_buffer_pct = 0.01\ncash_buffer_abs = 0",
        "cash_buffer_type = abs\ncash_buffer_abs = -5",
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_model_weights_not_sum_to_one(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace("gltr = 0.20", "gltr = 0.25")
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_accounts_multiple_ids_whitespace(tmp_path: Path) -> None:
    content = (
        VALID_CONFIG
        + """\

[accounts]
ids =   ACC1,ACC2  ,  ACC3   
"""
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.accounts == Accounts(
        ids=["ACC1", "ACC2", "ACC3"], confirm_mode="per_account", pacing_sec=0.0
    )
    assert cfg.ibkr.account_id == "ACC1"
    # Existing fields unaffected
    assert cfg.execution.order_type == "market"


def test_accounts_single_id_precedence(tmp_path: Path) -> None:
    content = (
        VALID_CONFIG.replace("account_id = DUA071544", "account_id = SHOULD_IGNORE")
        + """\

[accounts]
ids = ONLY
"""
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.accounts == Accounts(
        ids=["ONLY"], confirm_mode="per_account", pacing_sec=0.0
    )
    assert cfg.ibkr.account_id == "ONLY"
    assert cfg.rebalance.min_order_usd == 500


def test_accounts_unknown_keys_ignored(tmp_path: Path) -> None:
    content = (
        VALID_CONFIG
        + """\

[accounts]
ids = ACC1, ACC2
unknown = something
"""
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.accounts == Accounts(
        ids=["ACC1", "ACC2"], confirm_mode="per_account", pacing_sec=0.0
    )
    assert cfg.ibkr.account_id == "ACC1"
    assert cfg.io.log_level == "INFO"


def test_accounts_pacing_sec_valid(tmp_path: Path) -> None:
    content = (
        VALID_CONFIG
        + """\

[accounts]
ids = ACC1, ACC2
pacing_sec = 2.5
"""
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.accounts == Accounts(
        ids=["ACC1", "ACC2"], confirm_mode="per_account", pacing_sec=2.5
    )


def test_accounts_pacing_sec_negative(tmp_path: Path) -> None:
    content = (
        VALID_CONFIG
        + """\

[accounts]
ids = ACC1
pacing_sec = -1
"""
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)
