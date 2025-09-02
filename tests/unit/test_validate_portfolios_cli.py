import subprocess
import sys
from pathlib import Path


def test_cli_ok(tmp_path: Path) -> None:
    csv = tmp_path / "pf.csv"
    csv.write_text("ETF,SMURF,BADASS,GLTR\nCASH,100%,100%,100%\n")
    result = subprocess.run(
        [sys.executable, "-m", "src.io.validate_portfolios", str(csv)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "OK"


def test_cli_error(tmp_path: Path) -> None:
    csv = tmp_path / "pf.csv"
    csv.write_text("ETF,SMURF,BADASS\nCASH,100%,100%\n")
    result = subprocess.run(
        [sys.executable, "-m", "src.io.validate_portfolios", str(csv)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "Missing columns" in result.stdout
