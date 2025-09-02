# IBKR ETF Rebalancer — Scaffold

Simple scaffold for an ETF portfolio rebalancer using the Interactive Brokers
API. It loads a settings file and portfolio CSV, previews the rebalance, and
demonstrates dry‑run versus confirmed execution so you can build out the real
trading logic.

## Quickstart (Windows PowerShell)

```powershell
cd ibkr-rebalancer
py -3.10 -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pre-commit install
pytest -q -m "not integration"
```

## Usage (placeholders)

### Validate configuration
```bash
python -m src.io.validate_config config/settings.ini
```

### Dry run
```bash
python src/rebalance.py --dry-run --config config/settings.ini --csv data/portfolios.csv
```

### Confirmed execution
```bash
python src/rebalance.py --confirm --config config/settings.ini --csv data/portfolios.csv
```
