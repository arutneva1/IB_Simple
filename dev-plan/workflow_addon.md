# Workflow — Multi-Account Rebalancing Add-On

This workflow describes how to implement the four phases of the SRS add-on. Each phase includes development, testing, and documentation steps.

---

## Phase 1 — Config plumbing & compatibility
1. Update configuration parser to handle `[accounts]` section.
2. Implement validation and precedence rules.
3. Add unit tests for parsing.
4. Update README with new configuration examples.

---

## Phase 2 — Per-account loop, snapshot & planning (dry-run only)
1. Implement main iteration loop over accounts.
2. Integrate `account_id` into snapshot, drift, and planning logic.
3. Implement preview output with clear account labels.
4. Add unit + integration tests with mocks.
5. Update README with dry-run usage and examples.

---

## Phase 3 — Confirmations, execution & reporting
1. Implement per-account confirmation.
2. Add global confirmation option.
3. Extend order builder to tag orders with correct account.
4. Write per-account CSV reports and an aggregate run summary.
5. Add unit + mock-broker tests for confirmations, orders, and reporting.
6. Update README with confirmation modes and reporting schema.

---

## Phase 4 — Hardening: risk controls, pacing, failures & final acceptance
1. Implement client lifecycle isolation and pacing between accounts.
2. Add failure isolation and exit code signaling.
3. Add fault-injection tests for broker errors and partial failures.
4. Update README with safeguards and failure-handling notes.
5. Document “Future Work” (parallelization/concurrency).
