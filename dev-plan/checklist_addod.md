# Checklist — Multi-Account Rebalancing Add-On

Use this checklist to track progress through each phase.

---

## Phase 1 — Config plumbing & compatibility
- [ ] Add `[accounts]` section to `settings.ini`
- [ ] Validate multiple IDs and confirm precedence
- [ ] Implement account overrides (future-proof parsing)
- [ ] Unit tests for parsing and compatibility
- [ ] Update README with config examples

---

## Phase 2 — Per-account loop, snapshot & planning (dry-run only)
- [ ] Implement iteration loop over accounts
- [ ] Inject `account_id` into snapshot and planning
- [ ] Generate per-account preview output
- [ ] Add tests for snapshot, planning, and error handling
- [ ] Update README with dry-run usage

---

## Phase 3 — Confirmations, execution & reporting
- [ ] Implement per-account confirmations
- [ ] Implement global confirmation option
- [ ] Tag orders with correct account IDs
- [ ] Write per-account CSVs
- [ ] Write aggregate run summary CSV
- [ ] Tests for confirmations, orders, reporting
- [ ] Update README with confirmation/reporting details

---

## Phase 4 — Hardening: risk controls, pacing, failures & final acceptance
- [ ] Implement client state isolation
- [ ] Add pacing/backoff between accounts
- [ ] Ensure error isolation across accounts
- [ ] Fault-injection tests for broker errors
- [ ] Update README with safeguards
- [ ] Add “Future Work” note for concurrency
