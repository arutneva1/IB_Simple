# IBKR ETF Rebalancer — Scaffold

Simple scaffold for an ETF portfolio rebalancer using the Interactive Brokers
API. It loads a settings file and portfolio CSV, previews the rebalance, and
demonstrates dry‑run versus prompted execution so you can build out the real
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

The main rebalancer prints a batch summary preview before submitting trades.

### Dry run
Launch IB Gateway or Trader Workstation, then run:

```bash
python src/rebalance.py --dry-run --config config/settings.ini --csv data/portfolios.csv
```
Displays the batch summary and exits without placing orders.

### Interactive execution
```bash
python src/rebalance.py --config config/settings.ini --csv data/portfolios.csv
```
Shows the preview and waits for `y` before trading.

### Non-interactive execution
```bash
python src/rebalance.py --yes --config config/settings.ini --csv data/portfolios.csv
```
Skips the confirmation prompt and submits orders immediately.

### Read-only guard
```bash
python src/rebalance.py --read-only --config config/settings.ini --csv data/portfolios.csv
```
Forces preview-only mode even if `--yes` is used.

### Reporting & logging
After a run, timestamped artifacts are written under `reports/`:

```text
reports/rebalance_pre_<timestamp>.csv   # state and intended trades
reports/rebalance_post_<timestamp>.csv  # execution results (omitted on --dry-run)
reports/rebalance_<timestamp>.log       # INFO/ERROR log output
```

### Order execution module
`src/broker/execution.py` submits the confirmed trades and supports IBKR's
Adaptive or Midprice algos via `execution.algo_preference`. If the selected
algo is rejected and `fallback_plain_market` is true, it retries with a plain
market order. When `rebalance.prefer_rth` is enabled, the module queries the
IBKR server clock and only proceeds between 09:30 and 16:00
America/New_York. Order submissions log each status transition with the symbol
and order ID, including retries when falling back to plain market orders. The
module waits up to `execution.commission_report_timeout` seconds for commission
reports before defaulting to zero commission.

### Execution integration test
Verify end-to-end submission against a paper account:

```powershell
$env:IBKR_HOST="127.0.0.1"
$env:IBKR_PORT="4002"
$env:IBKR_CLIENT_ID="7"
pytest -q tests/integration/test_execution_paper.py
```

The test skips if the connection variables are missing or, with
`rebalance.prefer_rth=true`, when run outside regular trading hours.
