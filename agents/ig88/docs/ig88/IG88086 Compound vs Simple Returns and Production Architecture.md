# IG88086 — Compound vs Simple Returns and Production Architecture

**Date:** 2026-04-21
**Status:** REFERENCE + ARCHITECTURE PLAN

---

## Part 1: Compound vs Simple Returns

### The Problem

Previous backtests reported **simple sum returns**: add up every trade's PnL% and call that the total return.

This is wrong because trading capital compounds — each trade starts from a different balance.

### Simple Sum (Wrong)

```
Trade 1: +5%   → $1,000 × 1.05 = $1,050
Trade 2: +5%   → $1,050 × 1.05 = $1,102.50
Trade 3: -3%   → $1,102.50 × 0.97 = $1,069.43

Simple sum:  +5% + 5% - 3% = +7.00%
Actual:      ($1,069.43 / $1,000) - 1 = +6.94%
```

Small difference here. But over 100+ trades with larger swings, the gap becomes massive.

### Compound (Correct)

```python
capital = starting_capital
for trade in trades:
    ret = (trade.pnl_pct / 100) * risk_fraction * leverage - fee
    capital *= (1 + ret)
total_return = (capital / starting_capital - 1) * 100
```

### Why It Matters — Real Numbers (NEAR 4H LONG, 5yr)

| Method | Return | $500 Becomes |
|--------|--------|-------------|
| Simple sum | +477% | $2,383 |
| Compound 10% risk / 1x | +16% | $578 |
| Compound 20% risk / 3x | +12,198% | $60,990 |

Simple sum **underestimates** aggressive sizing (compounding works FOR you on winners) and **overestimates** conservative sizing (ignores volatility drag from losses).

### Volatility Drag

The key insight: returns compound geometrically, not arithmetically.

```
Gain +50%, then lose -33%:
  Simple: +50% - 33% = +17%
  Compound: 1.50 × 0.67 = 1.005 → +0.5%

Lose -33%, then gain +50%:
  Same result. Sequence doesn't matter for 2 trades.
  But for many trades, high variance = lower compound return.
```

**High-variance strategies lose more to volatility drag than low-variance strategies with the same average return.**

This is why walk-forward OOS compound returns are much lower than full-sample: the OOS windows capture real losing streaks that drag down compounding.

### Reference Implementation

`scripts/compound_backtest.py` — runs all risk/leverage combos with proper compounding.

---

## Part 2: Production Architecture

### The Core Question

How do we monitor 14+ pairs across multiple venues simultaneously, detect signals on 4H candle closes, and execute within seconds — with a single agent brain?

### The Answer: Scripts Do Everything. The Agent Oversees.

**No inference is needed for the trading loop.** Every step is deterministic math or API calls:

| Task | Requires Inference? | Implementation |
|------|--------------------|--------------|
| Load OHLCV data | No | pandas read_parquet + API fetch |
| Compute SMA100, ATR | No | numpy calculation (~1ms per pair) |
| Detect crossover signal | No | `if c[i-1] <= sma[i-1] and c[i] > sma[i]` |
| Check position sizing | No | `risk * leverage * capital / price` |
| Submit swap order | No | HTTP POST to Jupiter API |
| Monitor stops | No | compare price to stop level |
| Handle API errors | No (mostly) | retry logic, fallback endpoints |

**The agent (inference) is needed for:**
- Deciding to override a signal in unusual conditions
- Investigating when something breaks
- Adapting strategy when market regime changes fundamentally
- Researching new pairs/venues
- Answering questions from Chris

### Proposed Production Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     CRON SCHEDULER                           │
│                                                              │
│  Every 4h:  ──→  scanner_4h.py  ──→  executor.py ──→ done  │
│  Every 1h:  ──→  monitor.py     ──→  exits       ──→ done  │
│  Daily:     ──→  reporter.py    ──→  summary     ──→ done  │
│  On-failure:──→  alert Chris via Matrix                     │
│                                                              │
│  Agent (IG-88): Reviews reports, handles exceptions          │
└─────────────────────────────────────────────────────────────┘
```

### Component 1: Signal Scanner (`scanner_4h.py`)

**Trigger:** Cron, every 4 hours aligned to 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
**Runtime:** ~2 seconds (load 14 parquet files, compute indicators, check crossovers)
**Output:** JSON signals file

```python
# Pseudocode
for pair in PAIRS:
    df = load_latest_4h(pair)
    sma100 = compute_sma(df['close'], 100)
    atr = compute_atr(df, 14)
    
    if crossover_detected(df['close'], sma100, direction='above'):
        if anti_whipsaw_pass(df['close'], sma100):
            signal = create_signal(pair, 'LONG', df['close'][-1], atr[-1])
            save_signal(signal)
```

**No inference. Pure math. Can run on any machine.**

### Component 2: Executor (`executor.py`)

**Trigger:** Signal file created by scanner
**Runtime:** ~5-10 seconds per trade (API latency)
**Actions:**
1. Read signal
2. Validate risk checks (position size, max exposure, correlation)
3. Fetch Jupiter Ultra Swap quote
4. Submit order
5. Confirm fill
6. Log to state file

```python
# Pseudocode
signal = load_signal()
if validate_risk(signal):
    quote = jupiter_quote(signal)
    tx = sign_transaction(quote, wallet)
    result = jupiter_swap(tx)
    log_trade(signal, result)
```

**No inference. API calls + signing.**

### Component 3: Position Monitor (`monitor.py`)

**Trigger:** Cron, every 1 hour
**Runtime:** ~1 second
**Actions:**
1. Load open positions
2. Fetch current prices
3. Check stop-loss levels
4. Check SMA100 cross-back exits
5. Execute exits if triggered

### Component 4: Reporter (`reporter.py`)

**Trigger:** Cron, daily at 00:00 UTC
**Runtime:** ~3 seconds
**Actions:**
1. Compute daily PnL
2. Count trades, wins, losses
3. Update equity curve
4. Post summary to Matrix

### Single Agent vs Multiple Agents

**Verdict: One agent is sufficient. Multiple agents would add complexity without benefit.**

| Scenario | Single Agent | Multiple Agents |
|----------|-------------|-----------------|
| 4H scanning 14 pairs | ✅ Script handles it | ❌ Coordination overhead |
| Multi-venue (Jupiter + Kraken) | ✅ Separate scripts per venue | ❌ Agents would duplicate logic |
| 1H + 4H timeframes | ✅ Separate crons per timeframe | ❌ Same strategy, no need for agents |
| Polymarket monitoring | ✅ Separate script, agent reviews | ❌ Different domain, no overlap |

**The bottleneck is NOT inference. The bottleneck is execution latency (API calls) and data freshness.**

Adding agents would:
- Increase failure modes (agent communication, state sync)
- Add latency (inference time on each decision)
- Waste resources (cloud inference costs)
- Create coordination complexity

Scripts are faster, more reliable, and cheaper.

### What About Inference Bottleneck?

Current IG-88 inference: Nous cloud (~2-5 seconds per response).

If the trading loop needed inference at every step:
- Scan 14 pairs: 14 × 3s = 42 seconds (too slow for 4H candle close window)
- Execute 3 trades: 3 × 3s = 9 seconds (acceptable but wasteful)

With scripts:
- Scan 14 pairs: ~2 seconds
- Execute 3 trades: ~15 seconds (API-bound, not compute-bound)

**Scripts are 20x faster than inference for the trading loop.**

### What We Need To Build

| Component | Status | Priority |
|-----------|--------|----------|
| `scanner_4h.py` | EXISTS (atr4h_paper_trader_v9.py) | ✅ Done |
| `executor.py` | NOT BUILT | 🔴 Critical |
| `monitor.py` | EXISTS (check_positions in v9) | ✅ Done |
| `reporter.py` | NOT BUILT | 🟡 Important |
| Cron for scanner | EXISTS (job 24c5861ee2f2) | ✅ Done |
| Cron for monitor | NOT BUILT | 🟡 Important |
| Cron for reporter | NOT BUILT | 🟢 Nice to have |
| Jupiter API integration | CLI exists, not scripted | 🔴 Critical |
| Wallet signing | CLI exists, not automated | 🔴 Critical |

### Execution Latency Budget

For 4H ATR strategy, we have a comfortable window:

```
4H candle closes at: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
Scanner runs at:     00:05, 04:05, 08:05, 12:05, 16:05, 20:05 UTC (5 min delay)
Signal detected:     00:05-00:07
Order submitted:     00:07-00:10
Fill confirmed:      00:10-00:15
```

Total latency from candle close to fill: **10-15 minutes.** For a strategy with avg hold time of 2-5 days and avg trade return of +1-3%, this is negligible.

Even if the scanner runs at +30 minutes (worst case), the entry price might shift 0.1-0.3% — well within the strategy's tolerance.

### Scaling To Multi-Venue

When we add dYdX/Hyperliquid/Polymarket:

```
scanner_4h.py
├── scan_jupiter_pairs()    → Jupiter perps signals
├── scan_dydx_pairs()       → dYdX signals  
└── scan_polymarket()       → Polymarket crypto events

executor.py
├── execute_jupiter(signal) → Jupiter swap
├── execute_dydx(signal)    → dYdX order
└── execute_polymarket()    → Polymarket buy/sell
```

Still one agent. Still scripts doing the work. The agent just gets a richer daily report to review.
