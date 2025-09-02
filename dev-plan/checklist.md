# checklist.md — Phase-by-Phase QA & Deliverables

Use this as a **living PR checklist**. Each phase must meet its acceptance items before merging.

---

## Milestone A — Foundations

### Phase A1 — Repo Scaffold & Local Environment
- [ ] Repo created and `main` branch protected
- [ ] Directory structure scaffolded (`src/`, `tests/`, `config/`, `data/`, `reports/`)
- [ ] `requirements.txt` or `pyproject.toml` committed
- [ ] `.editorconfig`, `.gitignore`, `.pre-commit-config.yaml` committed
- [ ] Virtual environment created; dependencies install without error
- [ ] `pre-commit install` works; `pre-commit run --all-files` passes
- [ ] `README.md` quickstart authored
- [ ] Placeholder unit test in `tests/unit/`
- [ ] `pytest -q` is green locally

### Phase A2 — CI Pipeline & Quality Gates
- [ ] `.github/workflows/ci.yaml` created (lint, format, unit tests)
- [ ] CI caches pip dependencies
- [ ] CI skips integration tests by default
- [ ] CI enforced on `main` branch
- [ ] CI green on PRs and `main`

---

## Milestone B — Inputs, Validation, & State

### Phase B1 — Config Loader & Validation
- [ ] `src/io/config_loader.py` implemented
- [ ] `[models]` weights sum ≈ 1.0 (±0.001)
- [ ] Required keys/types/ranges validated
- [ ] Clear `ConfigError` messages on failure
- [ ] Unit tests cover valid/invalid configs

### Phase B2 — CSV Parser & Portfolio Validation
- [ ] `src/io/portfolio_csv.py` implemented
- [ ] Blanks parsed as 0%; percent strings handled
- [ ] Per-model sums ≈ 100% (±0.01)
- [ ] If `CASH` present: Sum(assets)+CASH ≈ 100% (±0.01)
- [ ] ETF symbols validated against IBKR's list; unknown symbols abort
- [ ] Invalid CSV aborts with actionable error
- [ ] Unit tests cover CASH ±, malformed %, unknown columns

### Phase B3 — IBKR Connection & Snapshot (Paper)
- [ ] `src/broker/ibkr_client.py` implemented
- [ ] Connects via `ib_async`, fetches positions, cash, NetLiq
- [ ] **Ignores CAD cash** in calculations
- [ ] Pacing/backoff logic included
- [ ] Integration snapshot tested manually
- [ ] Unit tests with mocks for error paths

---

## Milestone C — Core Logic & Preview

### Phase C0 — Pricing Utility
- [ ] `src/core/pricing.py` implemented
- [ ] Honors `price_source` and `fallback_to_snapshot`
- [ ] Unit tests for price retrieval and snapshot fallback

### Phase C1 — Model Mixing & Target Builder
- [ ] `src/core/targets.py` implemented
- [ ] Builds final targets with model mix and CASH
- [ ] Handles missing symbols (treated as 0)
- [ ] Totals ≈ 100%
- [ ] Unit tests for vector math & edge cases

### Phase C2 — Drift, Triggers & Prioritization
- [ ] `src/core/drift.py` implemented
- [ ] Computes current vs target weights, drift % and $
- [ ] Implements `per_holding` and `total_drift`
- [ ] Applies soft guidelines; skips trades < `min_order_usd`
- [ ] Prioritizes by |drift|
- [ ] Unit tests with fixture scenarios

### Phase C3 — Sizing, Leverage Guard, Rounding, Cash Buffer
- [ ] `src/core/sizing.py` implemented
- [ ] Reserves `cash_buffer_pct`
- [ ] Rounds if `allow_fractional=false`
- [ ] Enforces leverage ≤ `max_leverage`
- [ ] Partial scaling by priority when needed
- [ ] Unit tests for cash/leverage/rounding edge cases
- [ ] Unit tests enforce `min_order_usd` after rounding

### Phase C4 — Preview & CLI Confirmation
- [ ] `src/core/preview.py` implemented
- [ ] `src/rebalance.py` orchestrates end-to-end
- [ ] CLI flags: `--dry-run`, `--confirm`, `--read-only`, `--config`, `--csv`
- [ ] Trade plan shows drift % and $; batch summary visible
- [ ] Y/N prompt blocks execution unless confirmed
- [ ] End-to-end dry-run tested with fixtures

---

## Milestone D — Execution & Reporting

### Phase D1 — Order Submission
- [ ] `src/broker/execution.py` implemented
- [ ] Market orders with preferred algo; fallback plain market
- [ ] Batch submission; track order IDs
- [ ] Respect `prefer_rth` (block outside RTH)
- [ ] Integration test with tiny paper trade
- [ ] Unit tests for rejection/partial fill paths

### Phase D2 — Reporting & Logging
- [ ] `src/io/reporting.py` implemented
- [ ] Timestamped CSV written to `reports/`
- [ ] CSV includes all SRS columns: `timestamp_run`, `account_id`, `symbol`, `is_cash`, `target_wt_pct`, `current_wt_pct`, `drift_pct`, `drift_usd`, `action`, `qty_shares`, `est_price`, `order_type`, `algo`, `est_value_usd`, `pre_gross_exposure`, `post_gross_exposure`, `pre_leverage`, `post_leverage`, `status`, `error`, `notes`
- [ ] Logs include INFO/ERROR messages for validation and order states
- [ ] Unit tests check CSV schema and content

---

## Milestone E — Hardening & Release

### Phase E1 — Resilience & UX Polish
- [ ] Improved pacing/backoff
- [ ] Human-friendly error messages
- [ ] Graceful Ctrl+C handling
- [ ] Consistent final summary on abort
- [ ] Sample `settings.ini` and `portfolios.csv` updated

### Phase E2 — Docs & Handoff
- [ ] `README.md` Quickstart updated
- [ ] `USAGE.md` with CLI examples and outputs
- [ ] SRS, plan.md, workflow.md, checklist.md linked
- [ ] PR template and contribution guidelines added
- [ ] New contributor can set up, dry-run, and paper trade using docs only

---

## Global PR Gates (Every Phase)
- [ ] Code + unit tests implemented
- [ ] Docs updated (README/USAGE/SRS/plan/workflow/checklist)
- [ ] No API credentials or other secrets committed; `.gitignore` covers sensitive files
- [ ] CI green; pre-commit clean
- [ ] Manual smoke test (dry-run or paper) demonstrated
- [ ] Follow-ups/issues logged for next phases

