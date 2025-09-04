# Phased Implementation Plan — Multi-Account Rebalancing Add-On

This document outlines a 4-phase plan to implement the SRS add-on for supporting multiple IBKR accounts.

---

## Phase 1 — Config plumbing & compatibility
**Scope**
- Add `[accounts]` section to `settings.ini` with `ids=` list and `confirm_mode=` (`per_account` default). 
- Parse (but do not yet enforce) future-proof per-account overrides; fall back to global values.

**Code tasks**
- INI parser updates + validation (non-empty IDs, dedupe, preserve order).
- App config object: `accounts.ids: List[str]`, `accounts.confirm_mode: Enum`.
- Wire config into dependency graph (no behavior switch yet).

**Tests (unit)**
- Parse multiple IDs, whitespace variants, and single-ID back-compat.
- Ensure unknown keys don’t crash.

**Docs**
- Update **README**: new `[accounts]` sample + explanation of precedence and defaults.
- Note the same `portfolios.csv` is shared across accounts.

**Exit criteria**
- App starts and exposes parsed accounts & confirm mode; existing single-account users unaffected.

---

## Phase 2 — Per-account loop, snapshot & planning (dry-run only)
**Scope**
- Implement the main account iteration loop (ordered as given).
- For each account: snapshot positions/cash/NetLiq (USD focus), compute drift vs shared final targets, run selection/sizing, and present a **per-account preview** (dry-run). No order placement yet.

**Code tasks**
- `for account_id in accounts:` orchestrator.
- Inject `account_id` through data fetch & planning pipeline.
- Clear, labeled preview rows: Account, symbol, drift %/$, qty, est value, pre/post leverage.

**Tests (unit + integration with mocks)**
- Mock IB client: verify per-account independent snapshots and planning calls.
- Validate drift/target math matches single-account results when run per account.
- Ensure error in one account is captured but loop continues (no trading yet).

**Docs**
- README: “Dry run across multiple accounts” section and sample output table; remind that global flags (`--dry-run`, `--yes`, `--read-only`) apply to *every* processed account.

**Exit criteria**
- `--dry-run` shows correct, account-scoped plans for N accounts with clear labeling.

---

## Phase 3 — Confirmations, execution & reporting
**Scope**
- Add confirmations: default **per-account**; optional **global** confirm that aggregates all planned orders then applies one Y/N to all.
- On confirmation, submit **batch market orders** (algo preferred, fallback) **tagged with the correct account**.
- Reporting: write **per-account CSVs** and an **aggregate run summary** with the specified columns.

**Code tasks**
- Confirmation UX paths: `per_account` and `global`.
- Order builder includes account code; guarantee no stale account state reuse.
- Writers: `reports/rebalance_<ACCOUNT>_<timestamp>.csv` and `reports/run_summary_<timestamp>.csv`.

**Tests (unit + mock-broker)**
- Per-account confirm accepts/declines independently.
- Global confirm: one Y/N drives all accounts.
- Orders appear under the correct account in mock paper flow.
- CSV schemas and run summary columns match spec.

**Docs**
- README sections: “Per-account vs Global confirmation,” “Order tagging by account,” “Run summary schema.”

**Exit criteria**
- Meets acceptance criteria for dry-run, confirmations, correct account tagging, per-account CSVs, and run summary.

---

## Phase 4 — Hardening: risk controls, pacing, failures & final acceptance
**Scope**
- Enforce controls: prevent cross-talk by resetting/re-instantiating client state per account; add brief pacing/backoff between accounts; enhance preview clarity to avoid account confusion.
- Error isolation: failures recorded per account; non-zero exit if any account failed.

**Code tasks**
- Client lifecycle isolation utilities.
- Backoff parameters (configurable).
- Exit-code policy & run-summary status.

**Tests**
- Fault-injection: one account throws broker error → others proceed; exit code signals partial failure.
- Concurrency deliberately absent (verify sequential ordering).

**Docs**
- README: “Operational notes & safeguards” (client isolation, pacing, failure semantics).
- **Add a short “Future Work” note** explicitly calling out **Parallelization/concurrency** as a potential next step (kept out of v1 scope).

**Exit criteria**
- Final acceptance: run succeeds end-to-end across ≥2 accounts in paper mode, with correct summaries and resilient failure handling.

---

