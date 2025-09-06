import subprocess
import sys
from pathlib import Path


def test_cli_ok() -> None:
    cfg = Path(__file__).resolve().parents[2] / "config" / "settings.ini"
    result = subprocess.run(
        [sys.executable, "-m", "src.io.validate_config", str(cfg)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "Config OK"


def test_cli_error(tmp_path: Path) -> None:
    bad_cfg = tmp_path / "settings.ini"
    bad_cfg.write_text(
        """
[ibkr]
host = 127.0.0.1
port = 4002
client_id = 42
read_only = true
"""
    )
    result = subprocess.run(
        [sys.executable, "-m", "src.io.validate_config", str(bad_cfg)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Missing section [accounts]" in result.stdout
