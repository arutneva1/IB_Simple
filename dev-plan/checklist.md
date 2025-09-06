# checklist.md — Phase-by-Phase QA & Deliverables

Use this as a **living PR checklist**. Each phase must meet its acceptance items before merging.

---

## Milestone A — Foundations

### Phase A1 — Repo Scaffold & Local Environment
- [x] Repo created and `main` branch protected
- [x] Directory structure scaffolded (`src/`, `tests/`, `config/`, `data/`, `reports/`)
- [x] `requirements.txt`, `requirements-dev.txt` or `pyproject.toml` committed
- [x] `.editorconfig`, `.gitignore`, `.pre-commit-config.yaml` committed
- [x] Virtual environment created; dependencies install without error
- [x] `pre-commit install` works; `pre-commit run --all-files` passes
- [x] `README.md` quickstart authored
- [x] Placeholder unit test in `tests/unit/`
- [x] Placeholder integration test in `tests/integration/`
- [x] `pytest -q` is green locally

### Phase A2 — CI Pipeline & Quality Gates
- [x] `.github/workflows/ci.yaml` created (lint, format, unit tests)
- [x] CI caches pip dependencies
- [x] CI skips integration tests by default
- [x] CI enforced on `main` branch
- [x] CI green on PRs and `main`
- [x] CI runs ruff, black, isort, and mypy
- [x] Pull request template added (`.github/PULL_REQUEST_TEMPLATE.md`)

---

## Milestone B — Inputs, Validation, & State

### Phase B1 — Config Loader & Validation
- [x] `src/io/config_loader.py` implemented
- [x] `[models]` weights sum ≈ 1.0 (±0.001)
- [x] Required keys/types/ranges validated
- [x] Clear `ConfigError` messages on failure
- [x] Unit tests cover valid/invalid configs
- [x] Config validation via `load_config()`; no dedicated CLI

### Phase B2 — CSV Parser & Portfolio Validation
- [x] `src/io/portfolio_csv.py` implemented
- [x] Blanks parsed as 0%; percent strings handled
- [x] Per-model sums ≈ 100% (±0.01)
- [x] If `CASH` present: Sum(assets)+CASH ≈ 100% (±0.01)
- [x] ETF symbols validated against IBKR's list; unknown symbols abort
- [x] Invalid CSV aborts with actionable error
- [x] Unit tests cover CASH ±, malformed %, unknown columns

### Phase B3 — IBKR Connection & Snapshot (Paper)
- [x] `src/broker/ibkr_client.py` implemented
- [x] Connects via `ib_async`, fetches positions, cash, NetLiq
- [x] **Ignores CAD cash** in calculations
- [x] Pacing/backoff logic included
- [x] Integration snapshot tested manually
- [x] Unit tests with mocks for error paths

---

## Milestone C — Core Logic & Preview

### Phase C0 — Pricing Utility
- [x] `src/core/pricing.py` implemented
- [x] Honors `price_source` and `fallback_to_snapshot`
- [x] Unit tests for price retrieval and snapshot fallback

### Phase C1 — Model Mixing & Target Builder
- [x] `src/core/targets.py` implemented
- [x] Builds final targets with model mix and CASH
- [x] Handles missing symbols (treated as 0)
- [x] Totals ≈ 100%
- [x] Unit tests for missing symbols, CASH handling, and totals

### Phase C2 — Drift, Triggers & Prioritization
- [x] `src/core/drift.py` implemented
- [x] Computes current vs target weights, drift % and $
- [x] Implements `per_holding` and `total_drift` triggers
- [x] Applies soft guidelines; skips trades < `min_order_usd`
- [x] Prioritizes by |drift|
- [x] Unit tests cover trigger modes, min-order filtering, and prioritization

### Phase C3 — Sizing, Leverage Guard, Rounding, Cash Buffer
- [x] `src/core/sizing.py` implemented
- [x] Reserves cash buffer per configuration
- [x] Rounds if `allow_fractional=false`
- [x] Enforces leverage ≤ `max_leverage`
- [x] Partial scaling by priority when needed
- [x] Unit tests for cash/leverage/rounding edge cases
- [X] Unit tests enforce `min_order_usd` after rounding

### Phase C4 — Preview & CLI Confirmation
- [x] `src/core/preview.py` implemented with batch summary preview
- [x] `src/rebalance.py` orchestrates end-to-end
- [x] CLI flags: `--dry-run`, `--confirm`, `--read-only`, `--config`, `--csv`
- [x] Trade plan shows drift % and $; batch summary visible before prompt
- [x] Y/N prompt blocks execution unless confirmed
- [x] End-to-end dry-run tested with fixtures

---

## Milestone D — Execution & Reporting

### Phase D1 — Order Submission
- [x] `src/broker/execution.py` implemented
- [x] Market orders with preferred algo; fallback plain market
- [x] Batch submission; track order IDs
- [x] Respect `trading_hours` (set outsideRth for extended hours)
- [x] Integration test with tiny paper trade
- [x] Unit tests for rejection/partial fill paths

_Follow-up:_ capture partial fill metrics and consider extended-hours support.

### Phase D2 — Reporting & Logging
- [x] `src/io/reporting.py` implemented
- [x] Timestamped CSV written to `reports/`
- [x] Pre-trade report generated
- [x] Post-trade report generated
- [x] Pre-trade CSV matches schema: `timestamp_run`, `account_id`, `symbol`, `is_cash`, `target_wt_pct`, `current_wt_pct`, `drift_pct`, `drift_usd`, `action`, `qty_shares`, `est_price`, `order_type`, `algo`, `est_value_usd`, `pre_gross_exposure`, `post_gross_exposure`, `pre_leverage`, `post_leverage`
- [x] Post-trade CSV matches schema: `timestamp_run`, `account_id`, `symbol`, `is_cash`, `target_wt_pct`, `current_wt_pct`, `drift_pct`, `drift_usd`, `action`, `qty_shares`, `est_price`, `order_type`, `algo`, `est_value_usd`, `pre_gross_exposure`, `post_gross_exposure`, `pre_leverage`, `post_leverage`, `status`, `error`, `notes`
- [x] Logs written to `reports/rebalance_<timestamp>.log` with INFO/ERROR messages for validation and order states
- [x] Logs note pre-trade report generation
- [x] Logs note post-trade report generation
- [x] Logs capture connection events and final summary
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
- [x] `README.md` Quickstart updated
- [ ] `USAGE.md` with CLI examples and outputs
- [ ] SRS, plan.md, workflow.md, checklist.md linked
- [ ] PR template and contribution guidelines added
- [ ] New contributor can set up, dry-run, and paper trade using docs only

---

## Global PR Gates (Every Phase)
- [ ] Code + unit tests implemented
- [x] Docs updated (README/USAGE/SRS/plan/workflow/checklist)
- [ ] No API credentials or other secrets committed; `.gitignore` covers sensitive files
- [ ] CI green; pre-commit clean
- [ ] Manual smoke test (dry-run or paper) demonstrated
- [ ] Follow-ups/issues logged for next phases

