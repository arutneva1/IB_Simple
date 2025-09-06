# IBKR ETF Rebalancer — Scaffold

Simple scaffold for an ETF portfolio rebalancer using the Interactive Brokers
API. It loads a settings file and portfolio CSV, previews the rebalance, and
demonstrates dry‑run versus prompted execution so you can build out the real
trading logic.

## Quickstart (Anaconda)

FIRST TIME
```bash
cd IB_Trade
conda create -n ibkr-rebal python=3.10 -y
conda activate ibkr-rebal
pip install -r requirements.txt
python -m src.rebalance --config config/settings.ini
```
FYI: The `-m` option tells Python to treat the following argument (src.rebalance) as a module name rather than a file path. 

Consecutive use
```bash
cd IB_Trade
python -m src.rebalance --config config/settings.ini
```

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

### Customize sample files

The repository includes example `config/settings.ini` and `config/portfolios.csv`.
Provide your own portfolio CSV next to `settings.ini` when using the tool. Make
copies of these files outside version control and edit them with your own IBKR
host and target weights. Account IDs are listed under the `[accounts]`
section:

```bash
cp config/settings.ini my_settings.ini
cp config/portfolios.csv my_portfolios.csv
```

Blank cells in the CSV represent 0% allocations. Use the copied files via
`--config my_settings.ini --csv my_portfolios.csv` when running the tools.

### Accounts block and confirmation modes

Add multiple account IDs by extending `settings.ini` with an `[accounts]`
section:

```ini
[accounts]
ids = DU111111, DU222222
confirm_mode = per_account        ; per_account | global
pacing_sec = 1                    ; seconds to pause between accounts
parallel = false                  ; true processes accounts concurrently
path = portfolios.csv        ; portfolio CSV (relative to settings.ini)
```

The same `portfolios.csv` applies to all listed accounts. `confirm_mode`
controls how the tool prompts for trade confirmation and can be overridden at
runtime via `--confirm-mode`:

* `per_account` (default) previews and confirms each account separately.
* `global` shows all account previews first, then prompts once for the batch.

`pacing_sec` throttles between accounts by pausing for the specified number of seconds.
Set `parallel = true` to plan and execute accounts concurrently. The same can
be enabled at runtime via `--parallel-accounts`. When running with
`confirm_mode = per_account` and interactive prompts (i.e., without `--yes`),
plans are computed concurrently but confirmations are serialized per account to
avoid overlapping prompts.

Paths in `[accounts]` and `[account:<ID>]` sections are resolved relative to
the directory containing `settings.ini`.

Example forcing a global prompt:

```bash
python src/rebalance.py --dry-run --confirm-mode global --config config/settings.ini --csv config/portfolios.csv
```

Orders sent to Interactive Brokers are tagged with the respective account code
so each account's trades remain isolated.

### Account-specific overrides

`settings.ini` may contain optional `[account:<ID>]` blocks to override
settings for a single account.  Values inside these blocks take precedence over
the global `[rebalance]` settings for that account only; other accounts continue
to use the global defaults.  Keys that are not specified fall back to the
global values.

Unknown options in an `[account:<ID>]` block are ignored and generate a warning.

```ini
[rebalance]
allow_fractional = false
min_order_usd = 50

[account:DU111111]
allow_fractional = true       ; only DU111111 allows fractional shares
min_order_usd = 10            ; lower minimum order just for DU111111
```

In this example, account `DU111111` can submit fractional orders as small as
$10 while all other accounts require whole-share orders of at least $50.

### Per-account portfolio files

By default all accounts share the CSV passed via `--csv`. Specify a separate
portfolio for an account by adding `path` inside the `[account:<ID>]` block.
Paths are resolved relative to the directory containing `settings.ini`:

```ini
[account:DU111111]
path = portfolios_DU111111.csv  # relative to settings.ini

[account:DU222222]
path = portfolios_DU222222.csv
```

Accounts without a `path` entry use the global CSV. `validate_portfolios --all`
needs a valid global CSV unless every account has an override. Example run
mixing global and per-account files:

```bash
python src/rebalance.py --config config/settings.ini --csv config/portfolios.csv
```

## Usage

### Validate configuration
```bash
python -m src.io.validate_config config/settings.ini
```

### Validate portfolio CSV
Validate a single CSV (or all configured per-account files when each account
has one):
```bash
python -m src.io.validate_portfolios --config config/settings.ini config/portfolios.csv

# if every account has a dedicated portfolio CSV, omit the global file
python -m src.io.validate_portfolios --config config/settings.ini
```
Validate all portfolio files including account-specific overrides:
```bash
python -m src.io.validate_portfolios --config config/settings.ini --all config/portfolios.csv
```
An active IBKR session (TWS or IB Gateway) must be running so the tool can
verify ticker symbols.

### Account snapshot
The standalone snapshot script has been removed. Use
`IBKRClient.snapshot` directly or run the `rebalance` CLI to view account
positions and cash.

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
python src/rebalance.py --dry-run --config config/settings.ini --csv config/portfolios.csv
```
Displays the batch summary and exits without placing orders.

### Dry run across multiple accounts
When `[accounts]` lists more than one ID, the rebalancer previews each
account in sequence. Run the same command to simulate the batch, or add
`--parallel-accounts` to process them concurrently. Per-account confirmations
remain serialized without `--yes` so prompts appear one at a time:

```bash
python src/rebalance.py --dry-run --parallel-accounts --config config/settings.ini --csv config/portfolios.csv
```

Each account prints its own table. Example output:

```text
┏━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━┓
┃ Account    ┃ Symbol  ┃ Target % ┃ Current % ┃ Drift % ┃ Drift $ ┃ Action ┃   Qty ┃ Est Value ┃
┡━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━┩
│ DU111111   │ SPY     │ 60.00    │ 55.00    │ -5.00    │ -500.00  │ BUY    │ 5.00  │ 2000.00   │
└────────────┴─────────┴──────────┴──────────┴──────────┴──────────┴────────┴───────┴───────────┘

Batch Summary
│ Gross Buy           │ 500.00 │
│ Gross Sell          │   0.00 │
│ Pre Gross Exposure  │ 10000.00 │
│ Pre Leverage        │   1.00 │
│ Post Gross Exposure │ 10500.00 │
│ Post Leverage       │   1.05 │

┏━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━┳━━━━━━━┳━━━━━━━━━━━┓
┃ Account    ┃ Symbol  ┃ Target % ┃ Current % ┃ Drift % ┃ Drift $ ┃ Action ┃   Qty ┃ Est Value ┃
┡━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━╇━━━━━━━╇━━━━━━━━━━━┩
│ DU222222   │ AGG     │ 40.00    │ 45.00    │  5.00    │  500.00  │ SELL   │ 5.00  │ 1000.00   │
└────────────┴─────────┴──────────┴──────────┴──────────┴──────────┴────────┴───────┴───────────┘

Batch Summary
│ Gross Buy           │   0.00 │
│ Gross Sell          │ 500.00 │
│ Pre Gross Exposure  │ 10000.00 │
│ Pre Leverage        │   1.00 │
│ Post Gross Exposure │  9500.00 │
│ Post Leverage       │   0.95 │
```

A run summary file `reports/run_summary_<timestamp>.csv` records one row per
account with columns such as `planned_orders`, `submitted`, `filled`, and
leverage metrics.

Flags such as `--dry-run`, `--yes`, and `--read-only` apply to every account
processed.

### Interactive execution
```bash
python src/rebalance.py --config config/settings.ini --csv config/portfolios.csv
```
Shows the preview and waits for `y` before trading.

### Non-interactive execution
```bash
python src/rebalance.py --yes --config config/settings.ini --csv config/portfolios.csv
```
Skips the confirmation prompt and submits orders immediately.

### Read-only guard
```bash
python src/rebalance.py --read-only --config config/settings.ini --csv config/portfolios.csv
```
Forces preview-only mode even if `--yes` is used.

### Reporting & logging
After a run, timestamped artifacts are written under `reports/`:

```text
reports/rebalance_pre_<account>_<timestamp>.csv   # state and intended trades per account
reports/rebalance_post_<account>_<timestamp>.csv  # execution results per account (omitted on --dry-run)
reports/run_summary_<timestamp>.csv               # per-account run summary
reports/rebalance_<timestamp>.log                 # INFO/ERROR log output
```

`run_summary_<timestamp>.csv` contains one row per account with the schema:

```text
timestamp_run,account_id,planned_orders,submitted,filled,rejected,buy_usd,sell_usd,pre_leverage,post_leverage,status,error
```

### Operational notes & safeguards

* **Client isolation** – Orders are tagged with each account code so activity
  remains separated. All accounts share the `[ibkr]` `client_id` in
  `config/settings.ini`; per-account client IDs are not currently supported, so
  use separate runs with different configs if distinct IDs are required.
* **Pacing and backoff** – Requests are throttled to respect IBKR pacing limits.
  The rebalancer backs off and retries when the API signals rate‑limit
  violations.
* **Failure exit semantics** – Fatal errors stop the run and exit with a
  non‑zero status after logging the issue so operators can review the partial
  state.

### Order execution module
`src/broker/execution.py` submits the confirmed trades and supports IBKR's
`none`, Adaptive, or Midprice algos via `execution.algo_preference`. When
`adaptive` is chosen, `execution.adaptive_priority` selects `Patient`,
`Normal`, or `Urgent`. Midprice uses the dedicated MIDPRICE order type pegged 
to the NBBO midpoint and may be rejected if the account lacks entitlement or the 
market does not support it.
Submitted orders are tagged with their account code so Interactive Brokers
books them correctly. If the selected algo is rejected and
`fallback_plain_market` is true, it retries with a plain market order. Trading hours are controlled by
`rebalance.trading_hours`: use `eth` to allow extended-hours trading (setting
`outsideRth=True` on market orders) or the default `rth` to rely on IBKR's
regular-hours enforcement. Order submissions log each status transition with
the symbol and order ID, including retries when falling back to plain market
orders. The module waits up to `execution.commission_report_timeout` seconds for
commission reports before defaulting to zero commission.

### Execution integration test
Verify end-to-end submission against a paper account:

```powershell
$env:IBKR_HOST="127.0.0.1"
$env:IBKR_PORT="4002"
$env:IBKR_CLIENT_ID="7"
pytest -q tests/integration/test_execution_paper.py
```

The test skips if the connection variables are missing or, with
`rebalance.trading_hours=rth`, when run outside regular trading hours.

## Future Work

Parallel execution or other concurrency features are intentionally left out of
the v1 scope. The current design processes accounts sequentially to keep
behavior predictable and easier to audit.
