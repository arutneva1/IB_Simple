# SRS — IBKR ETF Portfolio Rebalancer (Detailed v1)

**Author:** Julian  
**Implementer:** Python (intended for AI-assisted coding)  
**Target broker:** Interactive Brokers (IBKR) via `ib_async`  
**Universe:** Long-only US-listed ETFs, CASH (incl. margin via pseudo-symbol)  
**Runtime mode:** Live against IBKR (paper account initially)

---

## 1) Problem Statement & Goals

You maintain three model ETF portfolios (e.g., SMURF, BADASS, GLTR). The application must:

1) Load the three model portfolios from a single CSV.  
2) Combine them using configured model weights to produce a final target allocation by ETF.  
3) Read current account holdings from IBKR.  
4) Compute drift vs. targets.  
5) Generate a **rebalance plan** within tolerance bands and constraints.  
6) Present a **preview** (with $ and % drifts) and require an explicit **command-line confirmation (Y/N)** prior to placing orders.  
7) Place orders when confirmed, then produce **order-level CSV reports** and logs.

**Operation trigger:** Manual only (no scheduler).  
**Non‑Goals (v1):** tax‑lot selection, shorting, options/futures, multi‑currency optimization, dividend/interest handling.

---

## 2) Scope & Definitions

- **Model portfolio:** Named set of (ETF, target %) that sums to 100% within the model.
- **Model mix:** Global weights across the three models (e.g., SMURF=0.5, BADASS=0.3, GLTR=0.2). Must sum to 1.0 (±0.001 tolerance).
- **Final target weight (ETF _i_):** \( w_i = \sum_k m_k \times p_{k,i} \), where \(p_{k,i}=0\) if ETF _i_ not present in model _k_.
- **Drift:** Current portfolio weight – final target weight.
- **Tolerance band:** Threshold(s) determining if a holding triggers a trade (e.g., ±50 bps).
- **CASH pseudo‑symbol (margin):** Special CSV row "CASH". Positive target → hold cash. Negative target → use margin. Sum(assets) + CASH must equal 100% (±0.01).
- **Currencies:** **USD-only trading.** Account may hold CAD cash, but **CAD is ignored** for sizing/drift/NetLiq computations. (User will convert manually when needed.)
- **Dividends/interest:** Out of scope (balances will naturally accumulate as cash).

---

## 3) Inputs & Configuration

### 3.1 `portfolios.csv` (single file, “wide-by-model” format)
**Required columns:** `ETF, SMURF, BADASS, GLTR` with percentage strings (e.g., `33%`, `0%`, blank=0%).

**Validation rules (hard stop on error):**
- For each model column, the non‑CASH rows must sum to 100% (±0.01).
- If `CASH` row is present and **positive**, then Sum(assets)+CASH must equal 100% (±0.01).
- If `CASH` row is **negative** (margin), then Sum(assets)+CASH must equal 100% (±0.01).
- ETF symbols must be valid IBKR symbols (US ETFs; SMART routing by default).  
- Blank cells are treated as 0%.

**Refresh:** File is edited/updated periodically by user.

**Failure behavior:** Any violation above **aborts** execution with a clear, actionable error message (no partial run).

### 3.2 `settings.ini` (single global config)

```ini
[ibkr]
host = 127.0.0.1
port = 4002
client_id = 42
read_only = true      ; force read‑only API until explicitly disabled

[accounts]
ids = UXXXXXX         ; or DUXXXXXX for paper

[models]
smurf = 0.50
badass = 0.30
gltr  = 0.20          ; must sum to 1.00 (±0.001)

[rebalance]
trigger_mode = per_holding        ; per_holding | total_drift
per_holding_band_bps = 50         ; trade if |drift| > 0.50%
portfolio_total_band_bps = 100    ; used when trigger_mode=total_drift
min_order_usd = 500               ; ignore smaller trades
cash_buffer_type = pct            ; pct | abs
cash_buffer_pct = 0.01            ; when pct: reserve 1% of NetLiq as cash
cash_buffer_abs = 0               ; when abs: reserve this USD amount
allow_fractional = false          ; set true only if account supports it
max_leverage = 1.50               ; hard cap on gross (e.g., 150%)
trading_hours = rth               ; rth or eth (extended trading hours)

[pricing]
price_source = last               ; used for sizing/preview valuations
fallback_to_snapshot = true

[execution]
order_type = market               ; market only
algo_preference = none            ; none | adaptive | midprice
fallback_plain_market = true      ; fallback if algo unsupported
batch_orders = true               ; send in batches

[io]
report_dir = reports              ; CSVs & logs
log_level = INFO
```

**Notes:**
- One global config per install (no per-run override file).  

---

## 4) System Behavior & Workflow

### 4.1 High-level flow
1. **Startup**: load `settings.ini` → validate `models` sum ~ 1.0.  
2. **Load models**: read `portfolios.csv` → validate per §3.1 → build three model vectors.  
3. **Combine models**: compute **final target weights** per ETF from model mix. Add `CASH` if present.  
4. **Fetch account**: query IBKR for current positions, NetLiq, cash. Convert/normalize to **USD-only**. **Ignore CAD cash** in all sizing/drift logic.  
5. **Compute drift**: for each ETF (and CASH), compute current weight vs target.  
6. **Trigger selection**:
   - If `per_holding`: select holdings where `|drift| > per_holding_band_bps` and expected trade value ≥ `min_order_usd`.
   - If `total_drift`: compute portfolio-level drift; if above band, include holdings with largest drifts until total within band.
   - **Soft guideline**: If a triggering trade rounds to 0 shares or falls below `min_order_usd`, skip it.
7. **Prioritization**: when cash is insufficient, **largest absolute drift first**.
8. **Sizing**: size orders to move each position **toward** target, subject to:
   - reserving cash per `cash_buffer_type` (`pct` of NetLiq or `abs` amount).
   - `allow_fractional` (generally false) → round to whole shares.  
   - **Leverage guard**: size partially so post-trade **gross exposure / NetLiq ≤ max_leverage**. If cannot meet, reduce orders proportionally by drift priority list.
9. **Preview** (no orders yet):
   - Produce a **trade plan** table with **% drift and $ drift**, target weights, estimated $ values, estimated post-trade weights.
   - Show a **batch summary** (gross to buy/sell, est. exposure, leverage) before prompting.
   - Prompt **Y/N** at CLI.
10. **Execute** (on `Y`):
    - Submit **batch market orders** with preferred **algo** (`none`, `adaptive`, or `midprice`) when supported by IBKR; `none` or unsupported algos **fallback to plain market**.
    - Honor `trading_hours` (`eth` sets outsideRth for extended sessions).
    - Monitor orders until Filled/Cancelled.
11. **Report & Log**: write **timestamped CSV** for the run; include per-order fills; append human-readable log lines.  
12. **Exit**.

### 4.2 Command-line UX
All runs display the batch-summary preview before asking for confirmation.

- `python rebalance.py --confirm` → preview then optional order submission after Y/N prompt.
- `python rebalance.py --dry-run` → preview only; **no orders** possible (overrides `--confirm`).
- `python rebalance.py --read-only` → safety flag; shows preview but never trades even after Y.

**Confirmation prompt example:**
```
Trade plan ready. 8 orders (Buy $18,420 / Sell $6,250).  
Est. gross exposure: $112,300 | Est. leverage: 1.23x | Cash buffer: 1.0%
Proceed? [y/N]:
```

### 4.3 Batch submission semantics
- Orders for all selected symbols are grouped into **one batch** per preview confirmation.  
- If one order in the batch is rejected, execution continues for the rest; errors are recorded in the log and CSV.

---

## 5) Pricing & Execution

- **Sizing/preview valuation** uses `price_source` (last by default) with optional snapshot fallback.  
- **Order type:** **Market** only.  
- **Algo preference:** `none`, `adaptive`, or `midprice` if available for the symbol/venue.
- **Fallback:** If `algo_preference` is `none` or the selected algo is rejected/unsupported, **fallback to plain market**.
- **Trading hours:** `trading_hours=rth` submits only during regular trading hours. `eth` enables extended-hours execution.

---

## 6) Risk, Constraints, & Guards

- **Max leverage** (`gross / NetLiq`) must be ≤ `max_leverage` **after** proposed trades. If exceeded, size down **partially** (prioritizing largest drifts) until the constraint is satisfied.  
- **Maintenance buffer:** not actively enforced; keep for future extension.  
- **Min order size** (`min_order_usd`) enforced at sizing and trigger stages.  
- **No special safety lists**: do not check for halted/restricted ETFs beyond broker-level constraints.

---

## 7) Reporting & Logging (CSV + logs per run)

**Two files per run, timestamped**, saved under `reports/`:
- **Pre-trade report** (`rebalance_pre_<timestamp>.csv`): current positions, target weights, drift, and proposed trades.
- **Post-trade report** (`rebalance_post_<timestamp>.csv`): new positions, executed quantities/prices, and trade summaries.

**CSV columns (initial schema):**
- Shared: `timestamp_run`, `account_id`, `symbol`, `is_cash`
- Pre-trade only (planned fields): `target_wt_pct`, `current_wt_pct`, `drift_pct`, `drift_usd`, `action` (BUY/SELL/NONE), `qty_shares`, `est_price`, `order_type`, `algo`, `est_value_usd`, `pre_gross_exposure`, `post_gross_exposure` (est), `pre_leverage`, `post_leverage` (est)
- Post-trade only (executed fields): `new_qty_shares`, `new_wt_pct`, `exec_qty_shares`, `exec_price`, `exec_value_usd`, `post_gross_exposure` (actual), `post_leverage` (actual), `status` (Submitted/Filled/Rejected/Skipped), `error` (if any), `notes`

**Logs:** human-readable INFO/ERROR lines, including:
- Validation outcomes and exact reasons for aborts.  
- IBKR connection and pacing notices.  
- Each order state (Submitted/PartiallyFilled/Filled/Cancelled).  
- Final summary.

---

## 8) Detailed Algorithms

### 8.1 Target mixing
- Parse model columns (SMURF/BADASS/GLTR) into vectors of weights \( p_{k,i} \).  
- Multiply by model mix `m_k` and sum across models to produce final target weight per ETF.  
- Include `CASH` (positive = cash target; negative = margin target).

### 8.2 Current state & weights
- Fetch IBKR positions and balances for `account_id`.  
- Convert all valuations to **USD**.  
- **Ignore CAD cash** in NetLiq and cash used for sizing (CAD is treated as non-tradable for this app).  
- Compute current weights per ETF and CASH.

### 8.3 Drift & triggers (soft guidelines)
- `drift_pct = current_wt_pct – target_wt_pct`.  
- Select candidates:
  - Per holding: `|drift_pct| > per_holding_band_bps/10000` and est trade value ≥ `min_order_usd`.
  - Total drift (if enabled): include largest abs drifts until total falls within `portfolio_total_band_bps`.
- If rounding to whole shares causes the trade value to dip below `min_order_usd`, **skip**.

### 8.4 Sizing & leverage guard
- Size each trade to move toward target within available cash after reserving cash per `cash_buffer_type`.
- When cash is insufficient, sort by **abs(drift)** descending and fill greedily until out of cash.
- Compute projected **gross exposure** and **leverage**; if projected leverage > `max_leverage`, scale back lower-priority trades until compliant.

### 8.5 Execution
- Build orders as **market** with `algo_preference` (`none`, `adaptive`, or `midprice`) where supported; `none` or unsupported algos submit plain market orders.
- Submit in a **batch**; track order IDs; poll for status until terminal.

---

## 9) Error Handling & Failure Modes

**Validation (abort):**
- Model columns do not sum to 100% (±0.01).  
- Sum(assets)+CASH ≠ 100% (±0.01).  
- Unknown/duplicate symbols, malformed percentages, missing mandatory columns.  
- `models` weights do not sum to ~1.0.

**Runtime (continue where safe):**
- IBKR pacing/backoff → retry with exponential delays; if persistent, abort trading but still emit preview/report.
- Individual order rejected → record error, continue others; final status summarizes partial success.

**Logging:** All errors **embedded in main log** (no separate `errors.log`).

---

## 10) Security & Secrets

- No credentials stored in code. IBKR uses local TWS/Gateway session.  
- Config files contain only host/port/client/account IDs.

---

## 11) Dependencies & Environment

- **Python** 3.10+.  
- **Primary library**: `ib_async` (plus `pandas`, `configparser`, `pathlib`, `typing`, etc.).  
- OS: Windows 10+ (with TWS/Gateway running).  
- Project directories: `reports/` auto-created if missing.

---

## 12) Test Plan (initial)

1. **CSV validation**
   - Model sums correct/incorrect; CASH ± cases; malformed cells; duplicates.
2. **Model mixing**
   - Vectors combine correctly; symbols missing in one model resolve as 0.
3. **IBKR snapshot**
   - Positions fetched and normalized to USD; CAD cash ignored in NetLiq.
4. **Triggering**
   - Per-holding band works; `min_order_usd` respected; soft-skip behavior when rounding.
5. **Prioritization & leverage**
   - Greedy by |drift| when cash constrained; scaling to satisfy `max_leverage`.
6. **Preview**
   - Shows % and $ drift; batch summary; Y/N prompt; `--dry-run` and `--read-only` print only.
7. **Execution**
   - Algo market OK; fallback to plain market when algo unavailable.
8. **Reporting**
   - Timestamped CSV created with planned/executed orders and fills; logs include all state transitions.

---

## 13) Open Points / Future Extensions

- Queueing outside RTH (vs hard block).  
- Additional notifications (email/Slack) if desired later.  
- Per-symbol overrides (e.g., conId, exchange) via `[symbol_overrides]`.  
- Tax-aware logic and multi-currency handling (explicitly out-of-scope now).

