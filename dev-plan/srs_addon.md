# SRS Add‑on — Multi‑Account Rebalancing

**Context:** Extends the existing single‑account SRS to support **multiple IBKR accounts** that share the **same `portfolios.csv`** and global rules. Orders are executed **per account** in sequence (default) or concurrently (future).

---

## 1) Goals & Non‑Goals

**Goals**
1. Allow listing **multiple `account_id`s** in `settings.ini`.
2. For each listed account: fetch positions/cash/pricing → compute drift vs the same final targets → preview snapshot → (on confirmation) place orders → report.
3. Produce **separate timestamped CSV reports** per account and an **aggregate run summary**.
4. Maintain all existing safety rules (cash buffer, leverage, min order, RTH, etc.).

**Non‑Goals (v1)**
- FA allocation groups, account‑specific model mixes, or different portfolios per account.  
- Concurrency (single threaded sequence only).  
- Cross‑account cash/transfer handling.

---

## 2) Config Changes (`settings.ini`)

### 2.1 New `[accounts]` section
```ini
[accounts]
ids = DU111111, DU222222, DU333333   ; comma‑separated account codes
confirm_mode = per_account            ; per_account | global
```

### 2.2 Backward compatibility
- The existing single-account configuration must remain backward-compatible if only one ID is listed.
- If both present → New `[accounts]` section takes precedence.

### 2.3 Account‑specific overrides (future‑proof)
```ini
[account:DU111111]
allow_fractional = false
min_order_usd = 500
max_leverage = 1.50
```
If no per‑account override is given, use global values.

---

## 3) CLI & UX

- Default behavior: iterate through all included accounts and **prompt confirmation per account**.
- flag: `--dry-run`, `--yes`, and `--read-only`  shall apply to every account processed.
- New flag: `--confirm-mode global` to print each account's preview sequentially before a **single Y/N** that applies to all. (default remains `per_account`.)
- Preview clearly labels **Account**, **symbol**, **drift %/$**, **qty**, **est value**, **pre/post leverage**.

---

## 4) Behavior & Flow

For each account in the effective list (filtered, ordered as given):
1. **Snapshot** positions/cash/NetLiq for that account (USD only; ignore CAD cash).
2. **Compute drift** vs **shared final targets** built from `portfolios.csv` + model mix.
3. **Trigger selection & sizing** using the same global rules (or per‑account overrides if provided).
4. **Preview** the orders for each account individually. In `global` confirm mode, previews for all accounts are shown first and a single confirmation is collected afterward.
5. On **confirmation**, submit **batch market orders** (algo preferred, fallback to plain market) tagged with the **account code**.
6. **Reporting**: write `reports/rebalance_<ACCOUNT>_<timestamp>.csv` and append to `reports/run_summary_<timestamp>.csv`.
7. **Error isolation**: if one account fails (validation or broker error/rejection), record it and continue to the next; exit with non‑zero code if any account failed.

---

## 5) Data & Reporting

**Per‑account CSV columns** (unchanged) as `account_id` already present in reports.

**Aggregate run summary**
- Columns: `timestamp_run, account_id, planned_orders, submitted, filled, rejected, buy_usd, sell_usd, pre_leverage, post_leverage, status, error`.

---

## 6) Risks & Controls
- **Cross‑talk risk**: Ensure the order payload carries the correct `account` for each order; never reuse a client object with stale account state without resetting.
- **Pacing**: Running multiple accounts increases API load; add short sleeps/backoff between accounts.
- **Preview confusion**: Always display the **account code** prominently in preview and logs.

---

## 7) Expand tests
- Ensure coverage for parsing and processing multiple accounts.
- Add tests verifying list parsing, backward compatibility, and per-account iteration.
- Mock IBKR client to assert that each account ID triggers a separate rebalance call.

---

## 8) Acceptance Criteria
- Can run `--dry-run` across multiple accounts with distinct previews and no errors.
- Per‑account confirmation works; declines skip trading only for that account.
- Orders submitted to IBKR **appear under the correct account** (paper) and reach terminal states.
- Per‑account CSVs plus a run summary CSV are created.
- Failing one account does not block the rest; exit code signals partial failure.

---

## 9) Sample configuration and documentation
- Provide guidance for multi-account usage.
- Explain that the same `portfolios.csv` is applied to each account sequentially.
