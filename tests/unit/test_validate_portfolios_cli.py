import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[2]))

import src.io.portfolio_csv as portfolio_csv
import src.io.validate_portfolios as validate_portfolios


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

[portfolio:acc1]
path = acc1.csv
"""

    cfg_path = tmp_path / "settings.ini"
    cfg_path.write_text(config_text)

    global_csv = tmp_path / "global.csv"
    global_csv.write_text("ETF,SMURF,BADASS,GLTR\nCASH,100%,100%,100%\n")
    acct_csv = tmp_path / "acc1.csv"
    acct_csv.write_text("ETF,SMURF,BADASS,GLTR\nCASH,100%,100%,100%\n")

    seen: list[Path] = []

    orig_parse = portfolio_csv._parse_csv

    def fake_parse(path: Path, expected: list[str] | None = None):
        seen.append(Path(path).resolve())
        return orig_parse(path, expected)

    monkeypatch.setattr(portfolio_csv, "_parse_csv", fake_parse)

    asyncio.run(
        validate_portfolios.main(
            str(global_csv), config_path=str(cfg_path), validate_all=True
        )
    )

    assert {global_csv.resolve(), acct_csv.resolve()} == set(seen)
