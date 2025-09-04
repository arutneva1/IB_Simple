# 101 — Kid-Friendly Testing & Acceptance Guide (Multi-Account Add-On)

Here’s how a 12‑year‑old can test and accept each phase of the multi-account rebalancing add-on.

---

## Phase 1 – Config
**Goal:** The app reads multiple account IDs and a confirm mode without breaking single-account setups.

**Do this:**
```bat
conda activate ibkr-rebal
cd path\to\IB_Simple
pre-commit run --all-files
pytest -q
python - <<"PY"
from src.io import config_loader
cfg = config_loader.load("config\\settings.ini")
print(cfg.accounts.ids, cfg.accounts.confirm_mode)
PY
```
**What success looks like:**
- Pre-commit and pytest finish with no errors.
- The Python snippet prints the account IDs you added and the confirm mode.
- Removing the `[accounts]` section still works for one account.

**Accept Phase 1:** - [ ] Passed

---

## Phase 2 – Per-account loop
**Goal:** A dry run shows a separate preview for each account.

**Do this:**
```bat
conda activate ibkr-rebal
cd path\to\IB_Simple
pre-commit run --all-files
pytest -q
python -m src.rebalance --dry-run --config config\settings.ini --csv data\portfolios.csv
```
**What success looks like:**
- Pre-commit and pytest pass.
- The dry run prints a table for each account with clear labels.

**Accept Phase 2:** - [ ] Passed

---

## Phase 3 – Confirmations & reporting
**Goal:** You confirm per-account plans and get per-account CSV reports.

**Do this:**
```bat
conda activate ibkr-rebal
cd path\to\IB_Simple
pre-commit run --all-files
pytest -q
python -m src.rebalance --config config\settings.ini --csv data\portfolios.csv
```
When prompted for each account, type `y` and press Enter.
After it finishes:
```bat
dir reports
```
**What success looks like:**
- Each account asks for confirmation (or one global confirm if set).
- Orders appear in TWS under the right account.
- `reports` shows a CSV for each account plus a run summary file.

**Accept Phase 3:** - [ ] Passed

---

## Phase 4 – Hardening
**Goal:** The run stays stable even when one account has problems.

**Do this:**
```bat
conda activate ibkr-rebal
cd path\to\IB_Simple
pre-commit run --all-files
pytest -q
python -m src.rebalance --dry-run --config config\settings.ini --csv data\portfolios.csv
```
Try again with one fake account ID to see friendly errors.

**What success looks like:**
- Pre-commit and pytest pass.
- A bad account prints a clear error, but the other accounts keep going.
- The app exits with a warning if any account failed.

**Accept Phase 4:** - [ ] Passed

---
