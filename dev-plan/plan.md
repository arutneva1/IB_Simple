# Project Plan — IBKR ETF Rebalancer

**Doc type:** plan.md (project management plan)  
**Source SRS:** “SRS — IBKR ETF Portfolio Rebalancer (Detailed v1)”  
**MVP scope:** Live trading (via IBKR paper), manual trigger with preview + CLI Y/N  
**Testing/CI:** Unit + integration tests; GitHub Actions CI with pytest  
**Env:** Include local dev setup (Windows 10+, Python 3.10+, TWS/Gateway running)

---

## 0) Strategy Overview

- **Goal:** Deliver a safe, testable MVP that can fetch account state, compute drifts from model mix, preview a rebalance, and—on confirmation—submit **market orders** (adaptive/midprice preferred; fallback to plain market) in **batches**, then report results.
- **Approach:** Milestone-driven phases, each with acceptance criteria and checklists to keep momentum and CI discipline.
- **Risk posture:** Favor correctness, validation, and observability. Abort on CSV/model sum errors; skip trades below `min_order_usd`; ignore CAD cash.

---

## 1) Milestones & Phases

### Milestone A — Foundations

#### Phase A1: Repo scaffold & local environment
**Deliverables**
- `README.md` with quickstart
- Base repo structure:
  - `src/` (code), `tests/` (pytest), `reports/` (output), `config/` (sample `settings.ini`), `data/` (sample `portfolios.csv`)
- `.editorconfig`, `.gitignore`, `requirements.txt`, `requirements-dev.txt` / `pyproject.toml`
- `pre-commit` hooks (black, isort, ruff/flake8)

**Checklist**
- [ ] Install Python 3.10+ (Windows)  
- [ ] Create venv or conda env  
- [ ] Install dependencies (`pip install -r requirements.txt -r requirements-dev.txt`)  
- [ ] Configure pre-commit: `pre-commit install`

**Acceptance**
- `pytest -q` runs a placeholder test successfully in CI & locally
- `pre-commit` enforces style on commit

---

#### Phase A2: CI pipeline & quality gates
**Deliverables**
- `.github/workflows/ci.yaml` running: lint, type-check (mypy optional), tests, artifact upload for reports (if any)

**Checklist**
- [ ] Add GitHub Actions CI  
- [ ] Configure cache for pip  
- [ ] Fail on lint/test errors

**Acceptance**
- CI passes on `main` and PRs; failing tests block merges

---

#### Phase A3: Credential hygiene
**Deliverables**
- No API keys or account credentials committed to the repository
- `.gitignore` entries for `.env`, real `settings.ini`, and other sensitive files

**Checklist**
- [ ] Secrets stored outside the repo (env vars or untracked files)
- [ ] `.gitignore` prevents committing credential files

**Acceptance**
- Manual scan confirms repository is free of credentials

---

### Milestone B — Inputs, Validation, & State

#### Phase B1: Config loader & schema validation
**Deliverables**
- `src/io/config_loader.py` parses `settings.ini`, validates `models` sum (~1.0), and exposes structured config dataclasses
- Helpful error messages (abort on error)

**Tests (unit)**
- [ ] Missing sections/keys  
- [ ] Bad types / out-of-range values  
- [ ] Models sum not ≈ 1.0

**Acceptance**
- CLI `python -m src.io.validate_config config/settings.ini` prints OK or errors

---

#### Phase B2: CSV parser & model portfolio validation
**Deliverables**
- `src/io/portfolio_csv.py` reads `portfolios.csv` and validates:
  - Per-model asset sums ≈ 100% (±0.01)
  - If `CASH` present: `sum(assets)+CASH ≈ 100%`
  - Blank cells → 0%
  - Malformed percentages → error (abort)
  - Verifies each ETF symbol against IBKR's symbol list; abort on unknown symbols

**Tests (unit)**
- [ ] Correct sums, CASH ± cases
- [ ] Malformed percent
- [ ] Unknown columns, duplicates
- [ ] Unknown ETF symbol aborts

**Acceptance**
- CLI `python -m src.io.validate_portfolios data/portfolios.csv` prints OK or detailed errors

---

#### Phase B3: IBKR connection & account snapshot (paper)
**Deliverables**
- `src/broker/ibkr_client.py` (using `ib_async`): connect, fetch positions, cash, NetLiq
- **USD normalization**; **ignore CAD cash**
- Minimal backoff/pacing handling, structured exceptions

**Tests**
- (integration) Paper account: can fetch positions at least once and parse them
- (unit) Mocks for error paths

**Acceptance**
- CLI `python -m src.snapshot --config config/settings.ini` prints summary JSON of positions/cash

---

### Milestone C — Core Logic & Preview

#### Phase C0: Pricing utility
_Status: Implemented in [`src/core/pricing.py`](../src/core/pricing.py)._
**Deliverables**
- `src/core/pricing.py` retrieves market prices for symbols
- Honors `price_source` and optional `fallback_to_snapshot`

**Tests (unit)**
- [ ] Price lookup respects requested source
- [ ] Falls back to snapshot when live price unavailable

**Acceptance**
- Deterministic price mapping given sample snapshot and config

---

#### Phase C1: Model mixing & target builder
**Deliverables**
- `src/core/targets.py` combines model vectors with model mix to compute final target weights per symbol (incl. CASH)

**Tests (unit)**
- [x] Symbols missing in some models → treated as 0
- [x] CASH handling ±
- [x] Numerical stability summing to ≈ 100%
- Implemented in `tests/unit/test_targets.py`

**Acceptance**
- Deterministic outputs given sample CSV + config

---

#### Phase C2: Drift computation, triggers & prioritization
**Deliverables**
- `src/core/drift.py` calculates current vs target weights, drift % and $
- Trigger selection (`per_holding` vs `total_drift`) with soft guidelines
- `prioritize_by_drift` filters trades below `min_order_usd` and ranks by |drift|

**Tests (unit)**
- [x] Per-holding band logic
- [x] Total-drift logic
- [x] Skips below `min_order_usd`
- [x] Prioritization ranks by |drift|

**Acceptance**
- Fixture-driven scenarios match expected selected trades

---

#### Phase C3: Sizing, leverage guard, rounding, cash buffer
**Deliverables**
- `src/core/sizing.py` sizes orders to move toward target, reserves cash per `cash_buffer_type`, rounds to whole shares if `allow_fractional=false`, and enforces **post-trade leverage ≤ max_leverage** with partial scaling by priority
- Trades falling below `min_order_usd` after rounding are skipped

**Tests (unit)**
- [ ] Greedy by |drift| under cash limits  
- [ ] Leverage scaling works  
- [ ] Rounding edge-cases

**Acceptance**
- Scenario matrices produce expected quantities and exposure metrics

---

#### Phase C4: Preview & CLI confirmation
_Status: Completed with batch-summary preview._
**Deliverables**
- `src/core/preview.py` renders a tabular **trade plan** (drift in % and $) and batch summary (gross buy/sell, pre/post gross exposure & leverage) before confirmation
- `rebalance.py` orchestrates: load → snapshot → targets → drift → sizing → preview → **CLI Y/N**
- CLI flags: `--dry-run` (preview only), `--confirm` (execute after prompt), `--read-only` guard

**Tests**
- [x] End-to-end dry-run on sample data
- [x] Output formatting stable for CSV reporter

**Acceptance**
- Batch summary preview shows correct math; prompt works as specified

---

### Milestone D — Execution & Reporting

#### Phase D1: Order submission (market + algo; fallback plain market)
**Deliverables**
- `src/broker/execution.py` builds market orders, applies preferred algo (`adaptive`/`midprice`) if supported; else **fallback to plain market**
- Batch submission; track order IDs; poll states
- Respect `trading_hours` (outsideRth for extended hours, else rely on IBKR)

**Tests**
- (integration) Paper account: submit small trades on a safe ETF, verify terminal states
- (unit/mocked) Rejected order path; partial fills path

**Acceptance**
- Batch with >=1 live order fills on paper without errors

---

#### Phase D2: Reporting & logging
**Deliverables**
- `src/io/reporting.py` writes **timestamped CSV** reports per run under `reports/`:
  - **pre-trade** with columns `timestamp_run`, `account_id`, `symbol`, `is_cash`, `target_wt_pct`, `current_wt_pct`, `drift_pct`, `drift_usd`, `action`, `qty_shares`, `est_price`, `order_type`, `algo`, `est_value_usd`, `pre_gross_exposure`, `post_gross_exposure`, `pre_leverage`, `post_leverage`
  - **post-trade** with columns `timestamp_run`, `account_id`, `symbol`, `qty_shares`, `fill_price`, `fill_value_usd`, `post_gross_exposure`, `post_leverage`, `status`, `error`, `notes`
- Unified logs (INFO/ERROR) embedded in main log

**Tests**
- [ ] Pre-trade and post-trade CSV schemas round-trip in tests
- [ ] Post-trade rows reflect executed orders (qty, fill price)
- [ ] Log messages include IBKR connection events, pacing/backoff notices, validation failures, order states, and final run summaries

**Acceptance**
- A full run generates both pre-trade and post-trade CSVs with expected rows/columns and correct post-trade content

---

### Milestone E — Hardening & MVP Release

#### Phase E1: Edge cases, resilience, and UX polish
**Deliverables**
- Better pacing/backoff; clearer error messages (abort early on invalid inputs)
- Cancellable run (Ctrl+C safe shutdown)
- Sample `portfolios.csv` and `settings.ini` with comments

**Tests**
- [ ] Intermittent IBKR connectivity (mock)  
- [ ] Abort paths leave no orphaned state

**Acceptance**
- Dry-run and live small-scale runs succeed across multiple days

---

#### Phase E2: Documentation & handoff
**Deliverables**
- `README.md` quickstart (dev + user)  
- `SRS.md` link and decision log  
- `USAGE.md` for CLI options and examples

**Acceptance**
- Another developer can set up, run dry-run, and place a test trade (paper) using docs only

---

## 2) Work Breakdown Structure (WBS)

1. **Infrastructure**: repo, env, CI, pre-commit  
2. **Config & CSV**: loaders, validators, error reporting  
3. **Broker**: IBKR client, snapshot, normalization  
4. **Logic**: targets, drift, trigger selection, sizing & leverage  
5. **UX**: preview table, CLI flow  
6. **Execution**: order builder, batch submit, state tracking  
7. **Reporting**: CSV schema, logs, artifacts  
8. **Hardening**: resilience, pacing, UX polish  
9. **Docs**: readme, usage, examples

---

## 3) Acceptance Criteria (MVP)

- ✅ Dry-run shows accurate **% and $ drift** and batch summary  
- ✅ On confirmation, batch **market** orders with algo (or fallback plain market) are submitted and reach terminal state in paper  
- ✅ Post-run CSV contains per-order details and pre/post exposure/leverage  
- ✅ CI green (lint + tests)  
- ✅ Abort on invalid `portfolios.csv` or invalid `settings.ini`

---

## 4) Environment Setup

1) **Windows + Python**
- Install Python 3.10+ (or Miniconda); ensure `python --version`
- Create env: `python -m venv .venv` (or `conda create -n ibkr-rebal python=3.10`)
- Activate env; `pip install -r requirements.txt -r requirements-dev.txt`

2) **IBKR TWS/Gateway**
- Install and run TWS or IB Gateway (paper)  
- Enable API, set host/port (default 127.0.0.1:4002), and your `account_id`  
- Ensure connectivity: sample snapshot command returns positions

3) **Pre-commit & CI**
- `pre-commit install`  
- Push to GitHub; confirm Actions CI runs and passes

---

## 5) Testing Strategy

- **Unit tests** for pure logic (config, CSV parsing, targets, drift, sizing)
- **Integration tests** (marked `@pytest.mark.integration`) that require:  
  - Paper account connection  
  - One or two safe ETFs (e.g., SPY/IAU) with tiny orders
- **Test data** fixtures for simple/edge cases

**Commands**
```bash
pytest -q
pytest -q -m integration  # optional
```

---

## 6) CI (GitHub Actions) — Sketch

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
          pip install pytest pytest-cov ruff black mypy
      - name: Lint & Format
        run: |
          ruff check .
          black --check .
      - name: Type check
        run: mypy src || true  # optional relax
      - name: Tests
        run: pytest -q --maxfail=1
```

> Note: Integration tests that require live IBKR should be **skipped in CI** (use marker) and run manually.

---

## 7) Operational Runbook (MVP)

1) Edit `config/settings.ini` and `data/portfolios.csv`  
2) Dry-run:
```bash
python rebalance.py --dry-run --config config/settings.ini --csv data/portfolios.csv
```
3) Live (paper):
```bash
python rebalance.py --confirm --config config/settings.ini --csv data/portfolios.csv
```
4) Inspect `reports/rebalance_*.csv` and logs

---

## 8) Risks & Mitigations

- **IBKR pacing/latency** → backoff, retries, small batch sizes
- **CSV/model mistakes** → strict validation, abort early with explicit errors
- **Algo unsupported for symbol** → fallback to plain market
- **RTH-only constraint** → initial block outside RTH; add queuing later if needed

---

## 9) Definitions of Done (per phase)

- Phase spec implemented  
- Unit tests added/passing  
- Docs updated  
- CI green  
- Demo (CLI command) works as described

---

## 10) Next Steps

- Start Milestone A (A1 → A2).  
- I can scaffold the repo (folders, placeholders, CI, sample config/CSV) immediately and attach a zip, or we continue iterating on this plan if you want tweaks first.

## Reporting & Logging

Each run writes timestamped CSV reports to `reports/`:

- `rebalance_pre_<timestamp>.csv`
- `rebalance_post_<timestamp>.csv`

Logs for the run are stored in `reports/rebalance_<timestamp>.log`.

