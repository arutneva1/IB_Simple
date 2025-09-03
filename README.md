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
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install
$env:PYTHONPATH = "."
pytest -q -m "not integration"
```

## Usage

### Validate configuration
```bash
python -m src.io.validate_config config/settings.ini
```

### Validate portfolio CSV
```bash
python -m src.io.validate_portfolios --config config/settings.ini data/portfolios.csv
```
An active IBKR session (TWS or IB Gateway) must be running so the tool can
verify ticker symbols.

### Account snapshot (paper)
```bash
python -m src.snapshot --config config/settings.ini
```
This step requires an IBKR paper account and serves as a manual integration test.
It returns positions and cash in USD, ignoring any CAD cash.

### Pricing utility
Retrieve a market price using [`src/core/pricing.py`](src/core/pricing.py):

```python
from src.core.pricing import get_price
# assume `ib` is a connected ib_async.IB instance
price = await get_price(ib, "SPY", price_source="last", fallback_to_snapshot=True)
```

### Drift preview
Generate a table of drift metrics:

```bash
python -m src.core.preview
```

### Dry run
Launch IB Gateway or Trader Workstation, then run:

```bash
python src/rebalance.py --dry-run --config config/settings.ini --csv data/portfolios.csv
```

### Confirmed execution
```bash
python src/rebalance.py --confirm --config config/settings.ini --csv data/portfolios.csv
```
