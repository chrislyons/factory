# Weakness Analysis & Optimization Opportunities — Portfolio v5 (IG88060)

**Date:** 2026-04-28
**Status:** Research document — proposes tests, not yet validated
**Source:** IG88060 doc, paper_trader_v4.py, backtest_engine.py, indicator_research.py, exit_parameter_sweep.py, h3b_volume_ignition_optimizer.py, deep_dive.py

---

## Executive Summary

Portfolio v5 has strong OOS stats overall (median 8.17x/yr Monte Carlo), but has two dangerous year-specific failures that the Monte Carlo doesn't capture because it shuffles trades independently. The 2023 regime destroyed all Keltner edges (PF 0.38) and barely saved by MACD (PF 1.02). The 2022 regime weakened both Keltner and MACD simultaneously. These correlated failures in specific regimes are the portfolio's Achilles heel. Five optimization opportunities are identified below.

---

## 1. The 2023 Failure: Keltner PF 0.38

### What happened

From IG88060 year-by-year table:

| Year | Keltner Edges | MACD Hist | Combined |
|------|---------------|-----------|----------|
| 2021 | PF 2.66-5.59  | PF 2.19   | Both profitable |
| 2022 | PF 1.33 (weak)| PF 0.78   | Both weak |
| 2023 | **PF 0.38**   | **PF 1.02** | MACD saves from total loss |
| 2024 | PF 18-39      | PF 2.70   | Both profitable |
| 2025 | PF 7-10       | PF 3.76   | Both profitable |

PF 0.38 means the Keltner edges lost 62 cents for every dollar gained — this is catastrophic at 30%+ allocation with 2x leverage.

### Regime conditions in 2023

2023 was a choppy recovery year for crypto:
- BTC rallied from ~$16.5k to ~$42k (+150%) but in a grinding, low-conviction fashion
- Many false breakouts: price would spike above Keltner bands then immediately reverse
- Volume was inconsistent — breakout bars didn't sustain follow-through
- ADX likely spent significant time below 25 (choppy/range-bound)
- The market was recovering from the 2022 Luna/FTX crash — participants were cautious, breakouts were faded

### Root cause analysis

The Keltner entry (close > EMA(20) + 2×ATR(14) + volume > 1.5×SMA(20) + ADX > 25) was designed for trending breakouts. In 2023:
- Breakouts above Keltner upper band were exhaustion moves, not initiation moves
- The 3.0x ATR trailing stop was too tight for the choppy environment — it gave back gains quickly
- Volume spikes were selling into strength, not accumulation

### Proposed regime filter

**YES — a regime filter can skip trades in this regime.** The system already has regime detection in `regime.py` (RISK_ON / NEUTRAL / RISK_OFF). Two approaches:

**Option A: BTC trend regime gate (existing infrastructure)**
The `build_btc_trend_regime()` function in `ichimoku_backtest.py` already classifies bars as RISK_ON/NEUTRAL/RISK_OFF based on BTC daily price vs SMA. Currently only Edge 1 (ETH Thu/Fri) and Edge 2 (ETH Vol Breakout) use ADX > 25, but NO edge uses the BTC regime gate.

Add: `regime[i] == RegimeState.RISK_ON` as a filter on ALL 4 Keltner edges. This would have blocked trades during the choppy recovery phases of 2023.

**Option B: ADX strengthening filter**
Instead of just ADX > 25, require ADX > 30 or ADX rising (ADX[i] > ADX[i-5]). This specifically targets the weak-trending, choppy environment that destroyed 2023.

**Recommendation:** Test Option A first (BTC regime gate). It's already built and validated for H3 strategies. The `SignalBacktester` class already has regime gating logic — just needs to be applied to the Keltner backtests.

### Impact estimate

If the BTC regime filter had blocked 2023's choppy phases, the Keltner PF could have gone from 0.38 to near-flat or slightly positive. With 30% allocation at 2x leverage, this could save ~20-40% portfolio drawdown in a 2023-type year.

---

## 2. The 2022 Failure: MACD PF 0.78 + Keltner Weakness

### What happened

In 2022, both Keltner (PF 1.33, barely positive) and MACD (PF 0.78, losing) were weak simultaneously. This is the worst-case scenario: 100% of the portfolio in correlated losing regimes.

### Regime conditions in 2022

2022 was a high-volatility bear market:
- Luna collapse (May 2022): -50%+ crash in days
- FTX collapse (Nov 2022): another -25% leg down
- BTC went from ~$47k to ~$16.5k (-65%)
- Extremely high volatility with violent mean-reverting swings
- VIX-equivalent (crypto fear/greed) was consistently extreme

### Can we add a regime filter for MACD?

**YES.** The MACD edge uses:
- Entry: MACD histogram turns positive AND close > EMA(50) AND volume > 1.2×SMA(20)
- Exit: 3.0x ATR trailing stop

The MACD histogram flip is a momentum-shift signal. In high-volatility bear markets (2022), these flips were whipsaws — the histogram would flip positive then immediately negative as price collapsed again.

**Proposed filter: Skip MACD entries when BTC daily close < EMA(50)**

This is simple and directly targets the 2022 problem. When BTC is below its 50-day EMA, the macro regime is bearish, and MACD histogram flips are likely bear-market rallies that fail. Implementation:

```python
# In eth_macd_hist_signal():
btc_close = get_btc_daily_close()  # Would need BTC data
btc_ema50 = compute_btc_ema50()
if btc_close < btc_ema50:
    return None  # Skip in bear market regime
```

Alternatively, use the existing `RegimeState.RISK_OFF` check. If regime == RISK_OFF, skip MACD entries.

**Impact estimate:** Filtering out bear-market MACD entries would have moved 2022 PF from 0.78 to ~1.0-1.2 (near breakeven or slightly positive). Combined with Keltner's PF 1.33, the portfolio would have been marginally positive in 2022 instead of mixed.

---

## 3. Volume Filter Sensitivity: 1.5x → 1.0x or 1.2x?

### Current state

The volume > 1.5×SMA(20) filter is used by 4 of 5 edges (all except MACD, which uses 1.2x). From the paper_trader_v4.py signal functions:

```python
# Edge 1, 3, 4: Keltner edges
volume[i] > 1.5 * vol_sma[i]

# Edge 2: Vol Breakout
volume[i] > 1.5 * vol_sma[i]

# Edge 5: MACD
volume[i] > 1.2 * vol_sma[i]
```

### Was 1.5x tested or just picked?

The `h3b_volume_ignition_optimizer.py` tested volume thresholds [1.3, 1.5, 1.8, 2.0] for the H3-B variant. The `momentum_breakout_backtest.py` grid includes VOL_MULTS = [1.5, 2.0, 2.5]. So 1.5x was tested in the context of H3-B and momentum breakout, but NOT specifically for the Keltner breakout signals used in Portfolio v5.

### What happens at 1.0x and 1.2x?

**Hypothesis A: Lower threshold adds noise**
- At 1.0x (volume just needs to be above average), you'd get ~50% more signals
- Many of these would be in low-conviction environments where breakouts fail
- Win rate would likely drop from ~53-68% to ~45-55%
- PF could degrade from 2.4-10.9 to 1.0-3.0

**Hypothesis B: Lower threshold captures real moves the 1.5x misses**
- Some legitimate breakouts have volume at 1.1-1.4x average
- These are "quiet accumulation" breakouts that sustain
- If the average winner at 1.2x volume is similar to 1.5x, the extra signals could be net positive

**The MACD edge already uses 1.2x successfully (PF 2.94)**, which suggests 1.2x is viable for at least momentum-shift signals. Whether it works for Keltner breakouts is an open question.

### Proposed test

Run a parameter sweep on the Keltner edges (Edges 1, 3, 4) with:
- Volume thresholds: [1.0, 1.2, 1.5, 2.0]
- Walk-forward 70/30 split
- Report: n, WR, PF, p-value per threshold per edge
- Special attention: does 1.2x add profitable signals in 2023 (the losing year)?

**Expected outcome:** 1.2x probably adds 20-30% more trades. If those trades have PF > 1.0 in OOS, it's worth keeping. If they have PF < 1.0, the 1.5x filter is doing its job.

### Risk

Testing multiple volume thresholds is a form of optimization that can overfit. Must use walk-forward and hold-out validation. The 1.5x value was likely chosen for a reason in the original Keltner research — it may represent a natural inflection point where breakout follow-through probability jumps.

---

## 4. ATR Trailing Stop Sensitivity: 3.0x and 4.0x

### Current state

| Edge | ATR Trailing Stop | Allocation |
|------|-------------------|------------|
| ETH Thu/Fri Keltner | 3.0x | 30% |
| ETH Vol Breakout | 4.0x | 25% |
| LINK Thu/Fri Keltner | 3.0x | 15% |
| ETH Week 2 Keltner | 3.0x | 15% |
| ETH MACD Histogram | 3.0x | 15% |

### Were these optimized or just picked?

The `exit_parameter_sweep.py` tested ATR trailing stops of [1.5, 2.0, 2.5] for H3 strategies on SOL 4h. The `atr_optimization.py` tested stop multipliers [1.0, 1.5, 2.0, 2.5, 3.0] and target multipliers [2.0, 3.5, 5.0, 6.5, 8.0]. The `momentum_breakout_backtest.py` grid includes TRAIL_MULTS = [2.0, 2.5, 3.0, 3.5].

However, these tests were on different strategies (H3-A, H3-B, momentum breakout) — NOT on the specific Keltner breakout signals used in Portfolio v5. The 3.0x and 4.0x values appear to have been selected based on general ATR research, not specific to these edges.

### Sensitivity analysis needed

The relationship between ATR multiplier and PF is typically non-linear:
- **Too tight (1.5-2.0x):** Stops out on noise, misses big moves, low avg win
- **Sweet spot (2.5-3.5x):** Rides trends, stops out on reversals, balanced WR/avg win
- **Too loose (4.0-5.0x):** Gives back profits, high avg loss, but catches full trends

The Vol Breakout edge using 4.0x (vs 3.0x for others) suggests it needs more room because its signals are earlier/noisier (ATR expansion signals, not price-breakout signals).

### Proposed test

Run ATR sensitivity sweep on each Keltner edge independently:
- ATR trailing multipliers: [2.0, 2.5, 3.0, 3.5, 4.0, 4.5]
- Walk-forward 70/30 split
- Report: n, WR, PF, avg_win%, avg_loss%, p-value per multiplier per edge
- Test on ETH daily data (match the actual trading timeframe)

**Key question:** Is 3.0x the optimal for Keltner edges, or is there a better value? And is 4.0x right for Vol Breakout, or should it be 3.5x or 4.5x?

### Risk of optimization

Testing 6 multiplier values × 4 edges = 24 configurations. With walk-forward, this is manageable but still risks overfitting to the specific 2021-2025 period. Out-of-sample validation on a hold-out period is critical.

---

## 5. Portfolio-Level Weakness: Correlated Regime Failure

### The real problem

The individual edge weaknesses (2023 Keltner, 2022 MACD) are symptoms of a deeper issue: **the portfolio has regime-correlated failures.** When the market is in a specific regime (2023 choppy recovery, 2022 bear crash), ALL edges degrade simultaneously.

The Monte Carlo projection (median 8.17x/yr, P(loss)=0.0%) is misleading because it assumes trade independence. In reality:
- Bad regimes cluster: 2022 and 2023 were consecutive bad years
- Correlation between edges increases in stress regimes
- The portfolio's actual worst case is worse than Monte Carlo suggests

### Proposed regime-aware portfolio construction

Instead of fixed allocations, consider dynamic allocation based on regime:

| Regime | Keltner Allocation | MACD Allocation | Cash |
|--------|-------------------|-----------------|------|
| RISK_ON (BTC trending up) | 85% | 15% | 0% |
| NEUTRAL (BTC range-bound) | 40% | 15% | 45% |
| RISK_OFF (BTC trending down) | 0% | 0% | 100% |

This would have:
- Fully deployed in 2021, 2024, 2025 (good years)
- Reduced exposure in 2023 (choppy) — saving the 0.38 PF Keltner losses
- Gone to cash in 2022 (bear crash) — avoiding both Keltner and MACD losses

### Implementation

The regime detection module (`regime.py`) already computes RISK_ON/NEUTRAL/RISK_OFF. The `paper_trader_v4.py` just needs to:
1. Fetch BTC daily data
2. Compute regime state
3. Scale position sizes by regime confidence

This is a portfolio-level filter, not an edge-level filter, and could dramatically reduce the worst-case drawdown years.

---

## Summary of Proposed Tests (Priority Order)

| Priority | Test | Expected Impact | Effort |
|----------|------|-----------------|--------|
| **1** | Add BTC regime gate to all Keltner edges | Could fix 2023 PF 0.38 → ~1.5+ | Low (code exists) |
| **2** | Add BTC < EMA(50) filter to MACD edge | Could fix 2022 PF 0.78 → ~1.2+ | Low (code exists) |
| **3** | ATR sensitivity sweep (2.0-4.5x) per edge | May find better stop widths | Medium (run sweep) |
| **4** | Volume threshold sweep (1.0-2.0x) on Keltner edges | May add signals or confirm 1.5x | Medium (run sweep) |
| **5** | Dynamic regime-based portfolio allocation | Dramatic worst-case improvement | Medium (needs logic) |

### Testing methodology for all

- Use ETH daily data (matching actual trading timeframe)
- Walk-forward: 70% train / 30% test minimum
- 5-split walk-forward for robustness
- Report OOS-only metrics: n, WR, PF, p-value, max DD
- Year-by-year breakdown (2021-2025) to specifically target 2022-2023
- Monte Carlo on filtered results to compare P(loss)

---

## Appendix A: Code Locations

| Component | File | Lines |
|-----------|------|-------|
| Edge signal definitions | `scripts/paper_trader_v4.py` | 122-222 |
| Backtest engine | `src/quant/backtest_engine.py` | 275-548 |
| Regime detection | `src/quant/regime.py` | 1-212 |
| BTC trend regime builder | `src/quant/ichimoku_backtest.py` | (build_btc_trend_regime) |
| Signal backtester with regime gate | `src/quant/indicator_research.py` | 79-200 |
| ATR optimization | `src/quant/atr_optimization.py` | 1-210 |
| Exit parameter sweep | `src/quant/exit_parameter_sweep.py` | 1-216 |
| Volume ignition optimizer | `src/quant/h3b_volume_ignition_optimizer.py` | 1-533 |
| Momentum breakout backtest | `src/quant/momentum_breakout_backtest.py` | 1-597 |

## Appendix B: Key Metrics Reference

IG88060 Portfolio v5 OOS stats (from doc):
- Monte Carlo median: 8.17x/yr
- P(≥2×): 99.8%
- P(≥5×): 83.1%
- P(loss): 0.0% (but this assumes trade independence — regime clustering invalidates this)
- 5th percentile: 3.51×
- 95th percentile: 20.23×

Edge OOS stats:
- Thu/Fri Keltner: PF 10.9, WR 68%, n=34, avg +10.54%
- Vol Breakout: PF 3.54, WR 46%, n=41, avg +5.67%
- LINK Thu/Fri: PF 2.41, WR 53%, n=53, avg +2.27%
- Week 2 Keltner: PF 4.16, WR 52%, n=71, avg +7.55%
- MACD Histogram: PF 2.94, WR 42%, n=31, avg +3.58%
