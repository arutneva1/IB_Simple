# workflow.md — IBKR ETF Rebalancer (Step‑by‑Step Implementation Guide)

**Audience:** You (Julian) and future contributors  
**Source docs:** SRS (Detailed v1), plan.md (Project Plan)  
**Goal:** Ship an MVP that **trades live on IBKR paper** with preview/confirm, market orders (adaptive/midprice preferred, fallback plain market), CSV reporting, and CI discipline.

---

## 0) Before You Start (One‑time)

1. **Decide repo name** (e.g., `ibkr-rebalancer`).  
2. **Create GitHub repo** (private).  
3. **Install** Python 3.10+ (or Miniconda) on Windows.
4. **Install** IBKR TWS or IB Gateway and enable API (127.0.0.1:4002).
5. **Prepare paper account** credentials and confirm it connects manually in TWS.
6. **Keep credentials out of version control** — store secrets in environment variables or gitignored files.

---

## 1) Milestone A — Foundations

### A1. Repo scaffold & local environment

**Create structure**
```
ibkr-rebalancer/
├─ src/
│  ├─ broker/           # IBKR client & order submission
│  ├─ core/             # targets, drift, sizing, preview
│  ├─ io/               # reporting, csv parsers, config loader
│  ├─ __init__.py
│  └─ rebalance.py      # CLI entrypoint/orchestrator
├─ tests/
│  ├─ unit/
│  └─ integration/
├─ data/
│  └─ portfolios.csv    # sample
├─ config/
│  └─ settings.ini      # sample
├─ reports/             # output (gitignored)
├─ README.md
├─ requirements.txt, requirements-dev.txt (or pyproject.toml)
├─ .pre-commit-config.yaml
├─ .editorconfig
├─ .gitignore
└─ LICENSE
```

**Set up environment**
```powershell
# Windows PowerShell
cd ibkr-rebalancer
py -3.10 -m venv .venv
. .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
pre-commit install
```

**Minimal `requirements.txt`**
```
pandas
ib_async
typing-extensions
pydantic>=2  # optional, helpful schemas
rich         # optional pretty CLI
click        # optional CLI flags
```

**`requirements-dev.txt`**
```
pytest
pytest-cov
ruff
black
isort
mypy         # optional
pre-commit
```

**.gitignore**
```
.venv/
reports/
__pycache__/
*.pyc
*.log
.pytest_cache/
```

**.editorconfig**
```
root = true
[*]
charset = utf-8
end_of_line = lf
insert_final_newline = true
indent_style = space
indent_size = 4
trim_trailing_whitespace = true
```

**.pre-commit-config.yaml**
```yaml
repos:
  - repo: https://github.com/psf/black
    rev: 24.4.2
    hooks:
      - id: black
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.5.7
    hooks:
      - id: ruff
        args: ["--fix"]
  - repo: https://github.com/pycqa/isort
    rev: 5.13.2
    hooks:
      - id: isort
```

**Sample data/config (edit with your real values)**

`config/settings.ini`
```ini
[ibkr]
host = 127.0.0.1
port = 4002
client_id = 42
account_id = DUXXXXXX
read_only = true

[models]
smurf = 0.50
badass = 0.30
gltr  = 0.20

[rebalance]
trigger_mode = per_holding
per_holding_band_bps = 50
portfolio_total_band_bps = 100
min_order_usd = 500
cash_buffer_pct = 1.0
allow_fractional = false
max_leverage = 1.50
maintenance_buffer_pct = 10
prefer_rth = true

[pricing]
price_source = last
fallback_to_snapshot = true

[execution]
order_type = market
algo_preference = adaptive
fallback_plain_market = true
batch_orders = true

[io]
report_dir = reports
log_level = INFO
```

`data/portfolios.csv` (example only)
```
ETF,SMURF,BADASS,GLTR
BLOK,,0%,
IBIT,,0%,
ETHA,,20%,
IAU,,27%,100%
GLD,,,0%
GDX,,,0%
CWB,0%,13%,0%
BIV,0%,0%,0%
BNDX,0%,,
VCIT,0%,13%,0%
SCHG,33%,9%,
SPY,34%,9%,
MGK,33%,9%,0%
CASH,0%,0%,0%
```

**Acceptance**
- `pre-commit run --all-files` succeeds  
- `pytest -q` (empty test placeholder) succeeds

---

### A2. CI pipeline & quality gates

**Add GitHub Actions** `.github/workflows/ci.yaml`
```yaml
name: CI
on: [push, pull_request]
jobs:
  build:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.10' }
      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt -r requirements-dev.txt
          pip install pytest pytest-cov ruff black isort mypy
      - name: Lint & Format
        run: |
          ruff check .
          black --check .
          isort --check-only .
      - name: Type check
        run: mypy src || true
      - name: Unit tests
        run: pytest -q -m "not integration" --maxfail=1 --disable-warnings
```
**Acceptance**: CI is green on main and PRs.

---

## 2) Milestone B — Inputs, Validation, & State

### B1. Config loader & schema validation

**Implement** `src/io/config_loader.py`
- Parse `settings.ini` with `configparser` or `pydantic` settings model.
- Validate: `[models]` sums ≈ 1.0 (±0.001); required keys present; numeric bounds sane.
- Raise `ConfigError` with actionable messages.

**Scaffold**
```python
# src/io/config_loader.py
from dataclasses import dataclass
from configparser import ConfigParser

@dataclass
class IBKR:
    host: str
    port: int
    client_id: int
    account_id: str
    read_only: bool

# ... other dataclasses: Models, Rebalance, Pricing, Execution, IO

class ConfigError(Exception):
    pass

def load_config(path: str):
    cp = ConfigParser()
    if not cp.read(path):
        raise ConfigError(f"Cannot read config: {path}")
    # parse into dataclasses + validations
    return cfg
```

**Tests** `tests/unit/test_config_loader.py`
- Missing sections/keys → error  
- `models` sum ≠ 1 → error  
- Good config → object with expected values

**Acceptance**
- `python -m src.io.config_loader config/settings.ini` (optional CLI) prints “OK” or clear errors

---

### B2. CSV parser & model portfolio validation

**Implement** `src/io/portfolio_csv.py`
- Read wide format (ETF, SMURF, BADASS, GLTR).
- Convert blanks to 0; parse `%` strings.
- Validate **per-model** sums ≈ 100% and **Sum(assets)+CASH ≈ 100%** when CASH present (±0.01).
- Return canonical dict: `{ symbol: {model: weight_float}, ... }`.
- After parsing, verify each ETF symbol against IBKR's symbol list; abort on unknown symbols.

**Tests** `tests/unit/test_portfolio_csv.py`
- Happy path; CASH positive; CASH negative; malformed `%` raises error.

**Acceptance**
- `python -m src.io.portfolio_csv data/portfolios.csv` prints “OK” or clear errors

---

### B3. IBKR connection & account snapshot (paper)

**Implement** `src/broker/ibkr_client.py`
- Connect via `ib_async`; fetch positions, cash, NetLiq (USD).  
- **Ignore CAD cash** for sizing/netliq computations.  
- Light backoff; structured exceptions.

**Tests**
- Integration: mark with `@pytest.mark.integration` to run manually.  
- Unit: mock client to simulate responses/errors.

**Acceptance**
- `python -m src.broker.ibkr_client --snapshot` shows JSON with positions/cash (paper account)

---

## 3) Milestone C — Core Logic & Preview

### C0. Pricing utility

`src/core/pricing.py` implemented.
- Fetch latest prices based on `price_source`
- If real-time price missing and `fallback_to_snapshot=true`, use snapshot values
- Wire into pipeline after snapshot retrieval and before drift/sizing calculations

**Tests**: unit tests for source selection and snapshot fallback.

---

### C1. Model mixing & target builder

**Implement** `src/core/targets.py`
- Build final target weights per ETF: `sum_k m_k * p_{k,i}`; add CASH if present.
- Ensure final totals ≈ 100%.

**Tests**: symbols missing in a model → treated as 0; CASH ± cases. Covered in `tests/unit/test_targets.py`.

---

### C2. Drift computation, triggers & prioritization

**Implement** `src/core/drift.py`
- Compute current wt % from snapshot (USD only).  
- `drift_pct = current - target` for ETFs + CASH.  
- Selection:
  - `per_holding`: `|drift| > band` and est trade value ≥ `min_order_usd`
  - `total_drift`: include largest abs drifts until total within band
- **Soft guidelines**: skip if rounding or value falls below `min_order_usd`.

**Tests**: fixture-driven scenarios.

---

### C3. Sizing, leverage guard, rounding, cash buffer

**Implement** `src/core/sizing.py`
- Reserve `cash_buffer_pct` of NetLiq.
- Round to whole shares when `allow_fractional=false`.
- Enforce **post-trade leverage ≤ max_leverage**; if exceeded, scale down lower-priority trades.
- Drop trades below `min_order_usd` once quantities are rounded.

**Tests**: cash constrained greedy fill, leverage scaling, rounding edge cases.

---

### C4. Preview & CLI confirmation

**Implement** `src/core/preview.py` and wire `src/rebalance.py`
- Render a tabular plan with drift **% and $** per symbol; batch summary: gross buy/sell, pre/post exposure & leverage.  
- CLI flags: `--dry-run`, `--confirm`, `--config`, `--csv`, `--read-only`.

**Preview example (console)**
```
Symbol  CurrWt%  TgtWt%  Drift%  Drift$   Action  Qty  EstPrice  EstValue$
SPY     23.10    25.00   +1.90   1900     BUY     5    380.00    1900
...
Batch: Buy $18,420 | Sell $6,250 | PreLev 1.21x → PostLev 1.23x | Cash buf 1.0%
Proceed? [y/N]:
```

**Tests**: E2E dry-run using fixtures.

---

## 4) Milestone D — Execution & Reporting

### D1. Order submission (market + algo; fallback plain market)

**Implement** `src/broker/execution.py`
- Build **market orders**; set algo preference (`adaptive`/`midprice`) where supported; else **fallback to plain market**.  
- Batch submit; track order IDs; poll until Filled/Rejected/Cancelled.  
- Respect `prefer_rth` (initially block with message if outside RTH).

**Tests**
- Integration (paper): tiny trade on a liquid ETF (e.g., SPY/IAU).  
- Unit/mocked: rejection paths, partial fills.

**Acceptance**
- One real paper trade batch runs to terminal states without error.

---

### D2. Reporting & logging

**Implement** `src/io/reporting.py`
- Write **timestamped CSV** per run under `reports/` with columns `timestamp_run`, `account_id`, `symbol`, `is_cash`, `target_wt_pct`, `current_wt_pct`, `drift_pct`, `drift_usd`, `action`, `qty_shares`, `est_price`, `order_type`, `algo`, `est_value_usd`, `pre_gross_exposure`, `post_gross_exposure`, `pre_leverage`, `post_leverage`, `status`, `error`, `notes`.
- Unified INFO/ERROR log lines; capture connection events, pacing/backoff messages, validation aborts, order states, and a final summary.

**Tests**: schema round-trip; presence of all SRS columns; status transitions captured.

---

## 5) Milestone E — Hardening & Release

### E1. Resilience & UX polish

- Improve pacing/backoff; clearer error messages (with remediation tips).  
- Graceful Ctrl+C; ensure no dangling state; final summary always printed.  
- Add `--read-only` safety and assert `read_only` is true in config unless `--confirm`.

**Tests**: simulated transient failures; abort flows.

---

### E2. Docs & Handoff

- Update `README.md` with Quickstart, Troubleshooting, IBKR tips.  
- Add `USAGE.md` with all CLI examples and expected outputs.  
- Link SRS + plan.md; include decision log for future maintainers.

**Acceptance**: A new contributor can set up, dry-run, and place a paper trade using only the docs.

---

## 6) Branching & Release Rhythm

- **Main** is protected (CI required).  
- Feature branches per phase (`feature/phase-b1-config`, etc.).  
- PR template with checklist: tests added, docs updated, CI green.  
- Tag MVP as `v0.1.0` once Milestones A–D complete.

---

## 7) Daily Driver Commands

```bash
# Lint/format/type check
pre-commit run --all-files
# (same as: ruff check . && black --check . && isort --check-only . && mypy src)

# Run unit tests only
pytest -q -m "not integration"

# Validate portfolio CSV
python -m src.io.validate_portfolios data/portfolios.csv

# Dry-run preview
python src/rebalance.py --dry-run --config config/settings.ini --csv data/portfolios.csv

# Live (paper) with confirmation
python src/rebalance.py --confirm --config config/settings.ini --csv data/portfolios.csv

# Show latest report
powershell -Command "Get-ChildItem reports | Sort-Object LastWriteTime -Descending | Select-Object -First 1"
```

---

## 8) Definition of Done per Phase (Quick Checklist)

- [ ] Code + unit tests implemented  
- [ ] CI green on PR  
- [ ] Docs updated (README/USAGE/SRS/plan/workflow)  
- [ ] Manual smoke (dry-run or paper trade) demonstrated  
- [ ] Issues/next steps captured

---

## 9) Known Non-Goals (v1)

- Lot-level tax logic, wash sales  
- Multi-currency optimization or FX trading  
- Notifications (email/Slack)  
- Non-market order types

---

## 10) Next Actions (today)

1. Create repo + scaffold (A1).  
2. Add CI (A2).  
3. Implement B1 → B2 with tests; commit and open PR.  
4. Implement B3 snapshot against paper; manual integration test.  
5. Proceed to Milestone C (targets → preview) and D (execution → reporting).

