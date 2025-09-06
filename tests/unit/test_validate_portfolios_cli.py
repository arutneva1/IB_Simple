import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

import src.io.validate_portfolios as validate_portfolios
from tests.unit.test_config_loader import VALID_CONFIG


def test_cli_ok(tmp_path: Path) -> None:
    csv = tmp_path / "pf.csv"
    csv.write_text("ETF,SMURF,BADASS,GLTR\nCASH,100%,100%,100%\n")
    cfg = Path(__file__).resolve().parents[2] / "config" / "settings.ini"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.io.validate_portfolios",
            "--config",
            str(cfg),
            str(csv),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "OK"


def test_cli_error(tmp_path: Path) -> None:
    csv = tmp_path / "pf.csv"
    csv.write_text("ETF,SMURF,BADASS\nCASH,100%,100%\n")
    cfg = Path(__file__).resolve().parents[2] / "config" / "settings.ini"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.io.validate_portfolios",
            "--config",
            str(cfg),
            str(csv),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Missing columns" in result.stdout


def test_cli_all_ok(tmp_path: Path) -> None:
    global_csv = tmp_path / "pf.csv"
    global_csv.write_text("ETF,SMURF,BADASS,GLTR\nCASH,100%,100%,100%\n")
    cfg = Path(__file__).resolve().parents[2] / "config" / "settings.ini"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.io.validate_portfolios",
            "--config",
            str(cfg),
            "--all",
            str(global_csv),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "OK"


def test_cli_all_error(tmp_path: Path) -> None:
    global_csv = tmp_path / "pf.csv"
    global_csv.write_text("ETF,SMURF,BADASS\nCASH,100%,100%\n")
    cfg = Path(__file__).resolve().parents[2] / "config" / "settings.ini"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.io.validate_portfolios",
            "--config",
            str(cfg),
            "--all",
            str(global_csv),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Missing columns" in result.stdout


def test_cli_all_reads_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure global and account-specific portfolio files are processed."""

    config_text = """\
[ibkr]
host = 127.0.0.1
port = 4002
client_id = 42
read_only = true

[accounts]
ids = ACC1, ACC2
confirm_mode = per_account

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
trading_hours = rth
max_passes = 3

[pricing]
price_source = last
fallback_to_snapshot = true

[execution]
order_type = market
algo_preference = adaptive
adaptive_priority = normal
fallback_plain_market = true
batch_orders = true
commission_report_timeout = 5.0
wait_before_fallback = 300

[io]
report_dir = reports
log_level = INFO

[account:ACC1]
path = acc1.csv
"""

    cfg_path = tmp_path / "settings.ini"
    cfg_path.write_text(config_text)

    global_csv = tmp_path / "global.csv"
    global_csv.write_text("ETF,SMURF,BADASS,GLTR\nCASH,100%,100%,100%\n")
    acct_csv = tmp_path / "acc1.csv"
    acct_csv.write_text("ETF,SMURF,BADASS,GLTR\nCASH,100%,100%,100%\n")

    seen: dict[str, Path] = {}

    orig = validate_portfolios.load_portfolios_map

    async def fake_load_portfolios_map(paths, *, host, port, client_id):  # noqa: ARG001
        seen.update({k: Path(v).resolve() for k, v in paths.items()})
        return await orig(paths, host=host, port=port, client_id=client_id)

    monkeypatch.setattr(
        validate_portfolios, "load_portfolios_map", fake_load_portfolios_map
    )

    other_dir = tmp_path / "other"
    other_dir.mkdir()
    monkeypatch.chdir(other_dir)

    asyncio.run(
        validate_portfolios.main(
            "global.csv", config_path=str(cfg_path), validate_all=True
        )
    )

    expected = {"ACC1": acct_csv.resolve(), "ACC2": global_csv.resolve()}
    assert seen == expected


def test_uses_accounts_path_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg_dir = tmp_path / "cfg"
    cfg_dir.mkdir()
    cfg_path = cfg_dir / "settings.ini"
    cfg_content = VALID_CONFIG.replace(
        "[accounts]\nids = ACC1, ACC2\n",
        "[accounts]\nids = ACC1, ACC2\npath = pf.csv\n",
    )
    cfg_path.write_text(cfg_content)
    csv_path = cfg_dir / "pf.csv"
    csv_path.write_text("ETF,SMURF,BADASS,GLTR\nCASH,100%,100%,100%\n")

    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)

    seen: list[Path] = []

    async def fake_load_portfolios(path, *, host, port, client_id):  # noqa: ARG001
        seen.append(Path(path).resolve())
        return {}

    monkeypatch.setattr(validate_portfolios, "load_portfolios", fake_load_portfolios)

    asyncio.run(validate_portfolios.main(config_path=str(cfg_path)))

    assert seen == [csv_path.resolve()]


def _all_accounts_config(tmp_path: Path) -> Path:
    config_text = """\
[ibkr]
host = 127.0.0.1
port = 4002
client_id = 42
read_only = true

[accounts]
ids = ACC1, ACC2
confirm_mode = per_account

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
trading_hours = rth
max_passes = 3

[pricing]
price_source = last
fallback_to_snapshot = true

[execution]
order_type = market
algo_preference = adaptive
adaptive_priority = normal
fallback_plain_market = true
batch_orders = true
commission_report_timeout = 5.0
wait_before_fallback = 300

[io]
report_dir = reports
log_level = INFO

[account:ACC1]
path = acc1.csv

[account:ACC2]
path = acc2.csv
"""
    cfg_path = tmp_path / "settings.ini"
    cfg_path.write_text(config_text)
    return cfg_path


def _write_two_csvs(tmp_path: Path) -> tuple[Path, Path]:
    acc1 = tmp_path / "acc1.csv"
    acc2 = tmp_path / "acc2.csv"
    content = "ETF,SMURF,BADASS,GLTR\nCASH,100%,100%,100%\n"
    acc1.write_text(content)
    acc2.write_text(content)
    return acc1, acc2


def test_cli_accounts_only(tmp_path: Path) -> None:
    cfg_path = _all_accounts_config(tmp_path)
    _write_two_csvs(tmp_path)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.io.validate_portfolios",
            "--config",
            str(cfg_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "OK"


def test_cli_ignores_global_when_all_accounts_provided(tmp_path: Path) -> None:
    cfg_path = _all_accounts_config(tmp_path)
    _write_two_csvs(tmp_path)
    missing = tmp_path / "missing.csv"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.io.validate_portfolios",
            "--config",
            str(cfg_path),
            str(missing),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "OK"
