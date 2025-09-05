import logging
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

from src.io.config_loader import (  # noqa: E402
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
    load_config,
    merge_account_overrides,
)

VALID_CONFIG = """\
[ibkr]
host = 127.0.0.1
port = 4002
client_id = 42
read_only = true

[accounts]
ids = ACC1, ACC2

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
max_passes = 3

[pricing]
price_source = last
fallback_to_snapshot = true

[execution]
order_type = market
algo_preference = adaptive
fallback_plain_market = true
batch_orders = true
commission_report_timeout = 5.0
wait_before_fallback = 300

[io]
report_dir = reports
log_level = INFO
"""


VALID_CONFIG_WITH_PORTFOLIO = VALID_CONFIG + "\n[Portfolio: acc1 ]\npath = foo.csv\n"


@pytest.fixture
def config_file(tmp_path: Path) -> Path:
    path = tmp_path / "settings.ini"
    path.write_text(VALID_CONFIG)
    return path


@pytest.fixture
def config_file_with_portfolio(tmp_path: Path) -> Path:
    path = tmp_path / "settings.ini"
    path.write_text(VALID_CONFIG_WITH_PORTFOLIO)
    return path


def test_load_valid_config(config_file: Path) -> None:
    cfg = load_config(config_file)
    expected = AppConfig(
        ibkr=IBKR(host="127.0.0.1", port=4002, client_id=42, read_only=True),
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
            max_passes=3,
        ),
        pricing=Pricing(price_source="last", fallback_to_snapshot=True),
        execution=Execution(
            order_type="market",
            algo_preference="adaptive",
            fallback_plain_market=True,
            batch_orders=True,
            commission_report_timeout=5.0,
            wait_before_fallback=300.0,
        ),
        io=IO(report_dir="reports", log_level="INFO"),
        accounts=Accounts(
            ids=["ACC1", "ACC2"],
            confirm_mode=ConfirmMode.PER_ACCOUNT,
            pacing_sec=0.0,
            parallel=False,
        ),
    )
    assert cfg == expected


def test_load_config_with_portfolio_section(
    config_file_with_portfolio: Path,
) -> None:
    cfg = load_config(config_file_with_portfolio)
    expected = {"ACC1": (config_file_with_portfolio.parent / "foo.csv").resolve()}
    assert cfg.portfolio_paths == expected


def test_portfolio_paths_resolve_from_config_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    portfolio_rel = Path("data/foo.csv")
    (cfg_dir / portfolio_rel).parent.mkdir(parents=True)
    (cfg_dir / portfolio_rel).write_text("")
    cfg_path = cfg_dir / "settings.ini"
    cfg_content = (
        VALID_CONFIG + f"\n[portfolio: acc1]\npath = {portfolio_rel.as_posix()}\n"
    )
    cfg_path.write_text(cfg_content)

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)

    cfg = load_config(cfg_path)

    assert cfg.portfolio_paths == {"ACC1": (cfg_dir / portfolio_rel).resolve()}


def test_missing_accounts_section(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace("\n[accounts]\nids = ACC1, ACC2\n", "\n")
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_accounts_invalid_confirm_mode(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "ids = ACC1, ACC2", "ids = ACC1, ACC2\nconfirm_mode = per_order"
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_accounts_pacing_sec_negative(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "ids = ACC1, ACC2", "ids = ACC1, ACC2\npacing_sec = -1"
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_accounts_ids_trim_and_deduplicate(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "ids = ACC1, ACC2",
        "ids =  acc1  ,  ACC2 , Acc1 ,acc2  ",
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.accounts.ids == ["ACC1", "ACC2"]


def test_accounts_parallel_flag(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "ids = ACC1, ACC2",
        "ids = ACC1, ACC2\nparallel = true",
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.accounts.parallel is True


def test_single_account_id(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace("ids = ACC1, ACC2", "ids =   acc1   ")
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.accounts.ids == ["ACC1"]


def test_account_section_unknown_keys(tmp_path: Path, caplog) -> None:
    content = VALID_CONFIG + "\n[account: acc1 ]\nfoo = bar\nunknown = baz\n"
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with caplog.at_level(logging.WARNING):
        cfg = load_config(path)
    assert cfg.accounts.ids == ["ACC1", "ACC2"]
    overrides = cfg.account_overrides["ACC1"]
    assert overrides.extra["foo"] == "bar"
    assert overrides.extra["unknown"] == "baz"
    messages = [rec.message.lower() for rec in caplog.records]
    assert any("unknown account override keys" in m for m in messages)


def test_ibkr_account_id_rejected(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "read_only = true", "read_only = true\naccount_id = DU111111"
    )
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


def test_model_weights_not_sum_to_one(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace("gltr = 0.20", "gltr = 0.25")
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_account_overrides_allow_fractional(tmp_path: Path) -> None:
    content = VALID_CONFIG + "\n[account: acc1 ]\nallow_fractional = true\n"
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.rebalance.allow_fractional is False
    cfg_acc = merge_account_overrides(cfg, "acc1")
    assert cfg_acc.rebalance.allow_fractional is True


def test_account_overrides_min_order_usd(tmp_path: Path) -> None:
    content = VALID_CONFIG + "\n[account: acc1 ]\nmin_order_usd = 100\n"
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.rebalance.min_order_usd == 500
    cfg_acc = merge_account_overrides(cfg, "acc1")
    assert cfg_acc.rebalance.min_order_usd == 100


def test_account_overrides_cash_buffer_abs(tmp_path: Path) -> None:
    content = (
        VALID_CONFIG
        + "\n[account: acc1 ]\n"
        + "cash_buffer_type = abs\n"
        + "cash_buffer_abs = 2500\n"
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.rebalance.cash_buffer_type == "pct"
    assert cfg.rebalance.cash_buffer_abs is None
    cfg_acc = merge_account_overrides(cfg, "acc1")
    assert cfg_acc.rebalance.cash_buffer_type == "abs"
    assert cfg_acc.rebalance.cash_buffer_abs == 2500


def test_account_id_normalization(tmp_path: Path) -> None:
    content = VALID_CONFIG.replace(
        "ids = ACC1, ACC2",
        "ids = acc1 , Acc2 ",
    )
    content += (
        "\n[Portfolio: acc1 ]\npath = foo.csv\n[account: Acc2]\nmin_order_usd = 100\n"
    )
    path = tmp_path / "settings.ini"
    path.write_text(content)
    cfg = load_config(path)
    assert cfg.accounts.ids == ["ACC1", "ACC2"]
    assert cfg.portfolio_paths["ACC1"] == (path.parent / "foo.csv").resolve()
    cfg_acc = merge_account_overrides(cfg, "acc2")
    assert cfg_acc.rebalance.min_order_usd == 100


def test_portfolio_override_unknown_account(tmp_path: Path) -> None:
    content = VALID_CONFIG_WITH_PORTFOLIO + "\n[Portfolio: acc3 ]\npath = foo.csv\n"
    path = tmp_path / "settings.ini"
    path.write_text(content)
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "ACC3" in str(exc.value)
