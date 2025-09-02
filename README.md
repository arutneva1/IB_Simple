# IBKR ETF Rebalancer — Scaffold

Minimal starter based on your SRS/plan/workflow. This scaffold compiles, runs, and gives you a place to start filling in logic.

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

## Dry run (placeholder)
```bash
python src/rebalance.py --dry-run --config config/settings.ini --csv data/portfolios.csv
```

## Live (paper) with confirm (placeholder)
```bash
python src/rebalance.py --confirm --config config/settings.ini --csv data/portfolios.csv
```
