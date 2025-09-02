# Pull Request Template — IBKR ETF Rebalancer

> Copy this file to `.github/pull_request_template.md` in your repo.

## Summary
- **What does this change do?**
- **Why is it needed?**
- **SRS/plan/workflow section(s) touched:**

## Linked Issues
- Closes #

## Changes
- [ ] Code changes
- [ ] Tests added/updated
- [ ] Docs updated (README/USAGE/SRS/plan/workflow/checklist)

## Screenshots / Logs (optional)

## Risk & Rollback Plan
- **Risk level:** Low / Medium / High  
- **Rollback:**

---

## Global PR Gates (must pass)
- [ ] CI green (`lint`, `format`, `unit`)  
- [ ] Pre-commit clean  
- [ ] Manual smoke test (dry-run or paper) demonstrated if applicable  
- [ ] Follow-ups/issues logged for next phase

---

<details>
<summary><strong>Milestone A — Foundations</strong></summary>

### Phase A1 — Repo Scaffold & Local Environment
- [ ] Repo created and `main` protected
- [ ] Structure scaffolded (`src/`, `tests/`, `config/`, `data/`, `reports/`)
- [ ] `requirements.txt` / `pyproject.toml` committed
- [ ] `.editorconfig`, `.gitignore`, `.pre-commit-config.yaml` committed
- [ ] Virtual env created; deps install clean
- [ ] `pre-commit run --all-files` passes
- [ ] `README.md` quickstart authored
- [ ] Placeholder unit test present; `pytest -q` green

### Phase A2 — CI Pipeline & Quality Gates
- [ ] `.github/workflows/ci.yaml` added (lint, format, unit tests)
- [ ] CI caches pip deps; skips integration by default
- [ ] CI required for merges to `main`
- [ ] CI green on PRs and `main`

</details>

<details>
<summary><strong>Milestone B — Inputs, Validation, & State</strong></summary>

### Phase B1 — Config Loader & Validation
- [ ] `src/io/config_loader.py` implemented
- [ ] `[models]` sum ≈ 1.0 (±0.001)
- [ ] Required keys/types/ranges validated
- [ ] Clear `ConfigError` messages; abort on failure
- [ ] Unit tests for valid/invalid configs

### Phase B2 — CSV Parser & Portfolio Validation
- [ ] `src/io/portfolio_csv.py` implemented
- [ ] Blanks → 0%; percent strings parsed; duplicates rejected
- [ ] Per-model sums ≈ 100% (±0.01)
- [ ] If `CASH` present: Sum(assets)+CASH ≈ 100% (±0.01)
- [ ] Invalid CSV aborts with actionable error
- [ ] Unit tests for CASH ±, malformed %, unknown columns

### Phase B3 — IBKR Connection & Snapshot (Paper)
- [ ] `src/broker/ibkr_client.py` connects via `ib_async`
- [ ] Fetches positions, cash, NetLiq (USD); **ignores CAD cash**
- [ ] Pacing/backoff & typed exceptions
- [ ] Integration snapshot tested manually
- [ ] Unit tests with mocks for error paths

</details>

<details>
<summary><strong>Milestone C — Core Logic & Preview</strong></summary>

### Phase C1 — Model Mixing & Target Builder
- [ ] `src/core/targets.py` builds final targets (incl. CASH)
- [ ] Missing symbols treated as 0; totals ≈ 100%
- [ ] Unit tests for vector math & edge cases

### Phase C2 — Drift, Triggers & Prioritization
- [ ] `src/core/drift.py` computes current/target wt, drift % and $
- [ ] Implements `per_holding` and `total_drift`
- [ ] Soft guidelines; skip < `min_order_usd`
- [ ] Prioritize by |drift| when cash-limited
- [ ] Unit tests with fixture scenarios

### Phase C3 — Sizing, Leverage Guard, Rounding, Cash Buffer
- [ ] `src/core/sizing.py` reserves cash buffer; rounds if `allow_fractional=false`
- [ ] Enforces post-trade leverage ≤ `max_leverage`; partial scaling when needed
- [ ] Unit tests for cash/leverage/rounding edge cases

### Phase C4 — Preview & CLI Confirmation
- [ ] `src/core/preview.py` renders tabular plan (drift % and $)
- [ ] `src/rebalance.py` orchestrates; CLI flags present (`--dry-run`, `--confirm`, `--read-only`, `--config`, `--csv`)
- [ ] E2E dry-run tested with fixtures; Y/N prompt works

</details>

<details>
<summary><strong>Milestone D — Execution & Reporting</strong></summary>

### Phase D1 — Order Submission (Market + Algo; Fallback Plain Market)
- [ ] `src/broker/execution.py` builds market orders; preferred algo if supported
- [ ] Fallback to **plain market** if algo unsupported/rejected
- [ ] Batch submission; track IDs; poll to terminal state
- [ ] Respect `prefer_rth` (block outside RTH)
- [ ] Integration test (paper) with tiny trade on liquid ETF
- [ ] Unit/mocked tests for rejection/partial fill paths

### Phase D2 — Reporting & Logging
- [ ] `src/io/reporting.py` writes **timestamped CSV** per run under `reports/`
- [ ] CSV includes: target/current wt, drift %/$, action, qty, est price/value, pre/post exposure & leverage, status, error
- [ ] Logs include validation & order states (INFO/ERROR)
- [ ] Unit tests check CSV schema and sample content

</details>

<details>
<summary><strong>Milestone E — Hardening & Release</strong></summary>

### Phase E1 — Resilience & UX Polish
- [ ] Improved pacing/backoff; human-friendly errors
- [ ] Graceful Ctrl+C; consistent final summary
- [ ] Samples updated: `settings.ini`, `portfolios.csv`

### Phase E2 — Docs & Handoff
- [ ] `README.md` Quickstart (dev + user)
- [ ] `USAGE.md` with CLI examples/outputs
- [ ] SRS/plan/workflow/checklist linked; change log updated
- [ ] Contribution guidelines and PR template added
- [ ] A new contributor can set up, dry-run, and paper trade using docs only

</details>

