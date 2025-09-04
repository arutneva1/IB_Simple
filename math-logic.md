# Math and Logic of the Rebalancer

## Introduction
This project is like a helpful robot that keeps an investment portfolio tidy. It automatically checks what you own and makes small trades so the mix stays on target. Think of it as a digital gardener trimming and watering your money plants so they grow the way you planned.

## How the main calculations work

### `core/targets.build_targets` – combining model weights
**What it is**
: Blends the suggestions from several models (like SMURF, BADASS, and GLTR) into one set of target percentages.

**Why it matters**
: Using more than one model spreads out the advice, so no single idea controls the portfolio.

**Example with numbers**
: If SPY has weights 60% (SMURF), 40% (BADASS), and 0% (GLTR) and the mix is 50% SMURF, 30% BADASS, 20% GLTR, the target for SPY becomes `0.5×60 + 0.3×40 + 0.2×0 = 42%`.

### `core/drift.compute_drift` – finding percent/dollar drift and action
**What it is**
: Compares what you own with the targets and figures out the difference (drift) in percent and dollars.

**Why it matters**
: Drift shows whether you need to buy or sell to get back on plan.

**Example with numbers**
: If AAPL should be 20% but is 15% of a $10,000 account, the drift is `15% - 20% = -5%`, or `-5% × 10,000 = -$500`, so the action is **BUY** $500 of AAPL.

### `core/drift.prioritize_by_drift` – filtering by minimum order size
**What it is**
: Drops drifts that are too small to trade and sorts the rest from biggest to smallest by dollars.

**Why it matters**
: Skipping tiny trades saves on fees and clutter.

**Example with numbers**
: With a $50 minimum, a $30 drift is ignored while a $70 drift makes the cut and is considered first.

### `core/sizing.size_orders` – allocating cash, enforcing buffers, calculating leverage
**What it is**
: Turns drift records into exact buy or sell orders while reserving extra cash and keeping leverage in check.

**Why it matters**
: Makes sure trades fit the available money and stay within safety limits.

**Example with numbers**
: If the account has $200 cash, a $10,000 net value, and a 1% cash buffer, only `$200 - 100 = $100` is available to buy. A requested $300 buy is scaled down to $100 unless later sells free up more cash. If buying would push exposure over a 1.5× leverage limit (`$15,000` for `$10,000` net value), the buys are trimmed until the limit is met.

**Example JG**
: Trade priorities come from the drift list fed into `size_orders`.
: `compute_drift` first creates the drift records in alphabetical order, giving a deterministic base order.
: `rioritize_by_drift` then sorts those records by absolute dollar drift in descending order while preserving any alphabetical tie. : That means smaller (or tied‑small) drifts end up at the end of the list.
: When leverage is too high, `size_orders` walks the trade list in reverse to trim buys starting from the tail—i.e., from the lowest‑priority drift.

### `core/pricing.get_price` – fetching prices and using fallbacks
**What it is**
: Asks Interactive Brokers for a price. If the main price field is missing, it tries a backup or a delayed snapshot.

**Why it matters**
: Trades need a reliable price; fallbacks prevent getting stuck.

**Example with numbers**
: Requesting the last price for MSFT might return nothing, so the code uses the close price of `$320`. If that is missing too and snapshots are allowed, it might fetch a delayed snapshot price of `$321`.

## Settings and what they do

### `ibkr.host`
**What it is**
: Address of the IBKR program to connect to.

**Why it matters**
: Without the right host, the rebalancer cannot talk to your broker.

**Example with numbers**
: `127.0.0.1` means "connect to the same computer I'm running on".

### `ibkr.port`
**What it is**
: Network port used for the IBKR connection.

**Why it matters**
: Using the wrong port is like knocking on the wrong door.

**Example with numbers**
: `4002` connects to the paper-trading gateway; `4001` would be for live trading.

### `ibkr.client_id`
**What it is**
: A number that identifies this program to IBKR.

**Why it matters**
: Each program needs a unique ID or messages get mixed up.

**Example with numbers**
: Setting `client_id = 1` works unless another session already uses 1.

### `ibkr.account_id`
**What it is**
: Your account number at IBKR.

**Why it matters**
: Trades are sent to this account.

**Example with numbers**
: Using `DU123456` points to a paper account; the real one might look like `U654321`.

### `ibkr.read_only`
**What it is**
: A switch that blocks trading when set to true.

**Why it matters**
: Lets you test without risking real trades.

**Example with numbers**
: With `read_only = true`, even a $500 drift results in **zero** trades.

### `models.smurf`, `models.badass`, `models.gltr`
**What they are**
: Fractions that tell how much each model contributes to the final mix.

**Why they matter**
: They control the blend in `build_targets`.

**Example with numbers**
: With weights `0.50`, `0.30`, and `0.20`, the models together add up to 1.0 or 100%.

### `rebalance.trigger_mode`
**What it is**
: Chooses how drift triggers trades: per holding or by total drift.

**Why it matters**
: It decides whether small individual drifts can trigger trades or if the portfolio must drift a lot overall.

**Example with numbers**
: With `per_holding`, a stock drifting 0.6% can trade if the band is 0.5%. With `total_drift`, trades happen only when the sum of drifts crosses the overall band.

### `rebalance.per_holding_band_bps`
**What it is**
: The per-holding drift band in basis points (bps).

**Why it matters**
: Prevents trading on tiny wiggles.

**Example with numbers**
: `50` bps equals `0.50%`; a 0.4% drift stays put, while 0.6% triggers a trade.

### `rebalance.portfolio_total_band_bps`
**What it is**
: Drift band for `total_drift` mode.

**Why it matters**
: Keeps the whole portfolio from trading unless it drifts past this threshold.

**Example with numbers**
: `100` bps equals `1%`; if all drifts add up to 0.8%, nothing happens, but at 1.2% trades begin.

### `rebalance.min_order_usd`
**What it is**
: Smallest dollar amount worth trading.

**Why it matters**
: Skips orders that cost more to execute than they are worth.

**Example with numbers**
: With `min_order_usd = 50`, a $40 trade is ignored, but a $55 trade proceeds.

### `rebalance.cash_buffer_type`
**What it is**
: Chooses how the cash buffer is defined: by percent (`pct`) or absolute dollars (`abs`).

**Why it matters**
: Determines how much cash stays untouched for safety.

**Example with numbers**
: `pct` reserves a slice of net value, while `abs` reserves a fixed amount.

### `rebalance.cash_buffer_pct`
**What it is**
: Percentage of net value to keep as cash when `cash_buffer_type = pct`.

**Why it matters**
: Keeps a rainy-day fund.

**Example with numbers**
: With `net_liq = $10,000` and `cash_buffer_pct = 0.01`, the code reserves `$10,000 × 0.01 = $100`.

### `rebalance.cash_buffer_abs`
**What it is**
: Dollar amount to keep when `cash_buffer_type = abs`.

**Why it matters**
: Guarantees a fixed cash cushion.

**Example with numbers**
: Setting `cash_buffer_abs = 200` leaves `$200` untouched, no matter the account size.

### `rebalance.allow_fractional`
**What it is**
: Allows buying or selling partial shares when true.

**Why it matters**
: Fractional shares let small accounts match targets more closely.

**Example with numbers**
: If a share costs $100 and you want $150 worth, `true` buys `1.5` shares; `false` buys only `1` share.

### `rebalance.max_leverage`
**What it is**
: Maximum allowed gross exposure divided by net value.

**Why it matters**
: Stops borrowing from getting out of hand.

**Example with numbers**
: With `max_leverage = 1.50` and `net_liq = $10,000`, exposure cannot exceed `$15,000`.

### `rebalance.maintenance_buffer_pct`
**What it is**
: Extra cushion for margin requirements (not enforced yet).

**Why it matters**
: Shows how much wiggle room the planner wants.

**Example with numbers**
: A `0.10` buffer hints at keeping `10%` of net value free for margin calls.

### `rebalance.prefer_rth`
**What it is**
: Trades only during Regular Trading Hours when true.

**Why it matters**
: Avoids thin after-hours markets.

**Example with numbers**
: With `prefer_rth = true`, a 6 p.m. trade waits until the market opens at 9:30 a.m.

### `pricing.price_source`
**What it is**
: Which price field to use: last, close, bid, or ask.

**Why it matters**
: Different fields suit different strategies.

**Example with numbers**
: `price_source = "bid"` uses the bid price, so selling 10 shares at a bid of $50 gives `$500`.

### `pricing.fallback_to_snapshot`
**What it is**
: Whether to try a delayed snapshot if real-time data is missing.

**Why it matters**
: Improves the chances of getting a usable price.

**Example with numbers**
: When the live feed is empty, a snapshot might return `$99.75` instead.

### `execution.order_type`
**What it is**
: The basic order style, here limited to market orders.

**Why it matters**
: Market orders trade quickly at whatever price is available.

**Example with numbers**
: Buying 5 shares with `order_type = market` fills near the current market price, say `5 × $20 = $100`.

### `execution.algo_preference`
**What it is**
: Preferred IBKR algo, like `adaptive` or `midprice`.

**Why it matters**
: Algos can try to get better prices or faster fills.

**Example with numbers**
: With `algo_preference = adaptive`, IBKR may slice a 100-share order into smaller pieces automatically.

### `execution.fallback_plain_market`
**What it is**
: Falls back to a simple market order if the chosen algo fails.

**Why it matters**
: Ensures trades still happen.

**Example with numbers**
: If the algo rejects a 20-share buy, `true` turns it into a normal market order for those 20 shares.

### `execution.batch_orders`
**What it is**
: Sends orders in batches instead of one at a time.

**Why it matters**
: Batching can be faster and easier to manage.

**Example with numbers**
: With `batch_orders = true`, ten trades might be sent as two batches of five.

### `execution.commission_report_timeout`
**What it is**
: How many seconds to wait for commission reports.

**Why it matters**
: Gives the broker time to send fee details.

**Example with numbers**
: `5.0` means the program waits up to five seconds before moving on.

### `io.report_dir`
**What it is**
: Folder where reports and logs are saved.

**Why it matters**
: Keeps records tidy and easy to find.

**Example with numbers**
: `reports` puts files into a folder named "reports" in the project.

### `io.log_level`
**What it is**
: How chatty the logging system is.

**Why it matters**
: Higher levels (like `DEBUG`) show more detail; lower levels (like `ERROR`) show less.

**Example with numbers**
: With `log_level = INFO`, normal messages appear, but debug details are hidden.
