import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.io.config_loader import (
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
cash_buffer_pct = 0.01
allow_fractional = false
max_leverage = 1.50
maintenance_buffer_pct = 0.10
prefer_rth = true

[pricing]
price_source = last
fallback_to_snapshot = true

[execution]
order_type = market
algo_preference = adaptive
fallback_plain_market = true
batch_orders = true

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
            cash_buffer_pct=0.01,
            allow_fractional=False,
            max_leverage=1.50,
            maintenance_buffer_pct=0.10,
            prefer_rth=True,
        ),
        pricing=Pricing(price_source="last", fallback_to_snapshot=True),
        execution=Execution(
            order_type="market",
            algo_preference="adaptive",
            fallback_plain_market=True,
            batch_orders=True,
        ),
        io=IO(report_dir="reports", log_level="INFO"),
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


def test_model_weights_not_sum_to_one(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace("gltr = 0.20", "gltr = 0.25")
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)
