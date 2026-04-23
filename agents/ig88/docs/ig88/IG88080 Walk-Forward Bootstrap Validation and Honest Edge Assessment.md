# IG88080 — Walk-Forward Bootstrap Validation and Honest Edge Assessment

**Date:** 2026-04-19
**Status:** ANALYSIS → STRATEGY REFINEMENT
**Objective:** Maximum sustained +PnL% with statistical rigor. Separate real edges from curve-fitting.

---

## Executive Summary

Walk-forward bootstrap validation of the ATR Breakout strategy across 7 pairs with adequate data (40K+ bars, 60m Binance) reveals that **most edges reported in IG88079 are NOT robust** when tested on rolling out-of-sample windows with bootstrap confidence intervals.

**Only 1 of 7 pairs passes all walk-forward splits.** This is a critical finding that requires honest reassessment before going live.

### Key Findings

| Finding | Impact |
|---------|--------|
| Only LINK long passes all 4/4 walk-forward splits | Portfolio is much smaller than claimed |
| ETH long has PF=0.23 in most recent split (Dec 2025-Apr 2026) | Strategy may be degrading |
| SOL short has 3/5 splits with PF < 1.0 | Short edge is NOT robust |
| NEAR long has 2/3 splits with PF < 1.0 | Previously reported as profitable — drop it |
| Previous IG88079 walk-forward was too lenient | Results were misleading |

---

## Part 1: Walk-Forward Methodology

**Data:** Binance 60m OHLCV, 40K+ bars per pair (Apr 2021 – Apr 2026)
**Method:** 5 rolling 70/30 train/test splits (no parameter optimization in-test)
**Bootstrap:** 2,000 resamples, 95% CI for PF, WR, return
**Strategy:** ATR Breakout (ATR=14, mult=2.0, trail=1.0%, SMA100 regime filter)

---

## Part 2: Long Strategy Results

### ETHUSDT LONG — Mixed (4/5 splits profitable)

```
Full sample: 225 trades, PF=1.60, WR=41.8%, Return=134%
Split 1 (Oct 24-Jan 25): PF=1.62, WR=45%, Return=+3.4%  [OK]
Split 2 (Jan 25-May 25): PF=9.71, WR=75%, Return=+37.1% [GREAT]
Split 3 (May 25-Sep 25): PF=1.63, WR=35%, Return=+7.6%  [OK]
Split 4 (Sep 25-Dec 25): PF=1.81, WR=44%, Return=+9.7%  [OK]
Split 5 (Dec 25-Apr 26): PF=0.23, WR=7%,  Return=-9.5%  [BAD — FAIL]
```

**Problem:** The most recent 4 months show PF=0.23 with 95% CI [0.00, 0.97]. The CI upper bound is BELOW 1.0 — meaning we can't reject the hypothesis that the strategy has no edge in the current regime.

**Regime analysis of the bad split:** -44% downtrend, 47% above SMA100, 65% annualized vol, +0.029 return autocorrelation. This looks similar to other splits that were profitable. The failure is NOT explained by obvious regime differences — suggesting potential overfitting to historical data or parameter sensitivity.

### AVAXUSDT LONG — Mostly Robust (4/5 profitable)

```
Full sample: 149 trades, PF=2.10, WR=54.4%, Return=162%
Split 1 (Oct 24-Jan 25): PF=0.33, WR=40%, Return=-2.1%  [BAD — FAIL]
Split 2 (Jan 25-May 25): PF=7.29, WR=78%, Return=+11.8% [GREAT]
Split 3 (May 25-Sep 25): PF=1.92, WR=60%, Return=+4.8%  [OK]
Split 4 (Sep 25-Dec 25): PF=2.83, WR=50%, Return=+5.6%  [GOOD]
Split 5 (Dec 25-Apr 26): PF=3.27, WR=53%, Return=+3.4%  [GOOD]
```

Bad split is the FIRST window only. Recent splits are consistent. **Acceptable for inclusion with caveats.**

### NEARUSDT LONG — NOT ROBUST (only 1/3 profitable)

```
Full sample: 148 trades, PF=1.36, WR=35.1%, Return=55%
Split 3 (May 25-Sep 25): PF=0.82, WR=29%, Return=-1.6%  [BAD]
Split 4 (Sep 25-Dec 25): PF=0.21, WR=14%, Return=-10.7% [BAD — FAIL]
Split 5 (Dec 25-Apr 26): PF=2.31, WR=60%, Return=+3.3%  [OK]
```

**2 of 3 splits are unprofitable.** Full-sample return of 55% is misleading — driven by one regime. **Drop from portfolio.**

### LINKUSDT LONG — ROBUST (4/4 profitable)

```
Full sample: 124 trades, PF=2.43, WR=47.6%, Return=170%
Split 2 (Jan 25-May 25): PF=1.10, WR=30%, Return=+0.5%  [MARGINAL]
Split 3 (May 25-Sep 25): PF=22.31, WR=83%, Return=+11.5% [GREAT]
Split 4 (Sep 25-Dec 25): PF=4.42, WR=50%, Return=+7.2%  [GOOD]
Split 5 (Dec 25-Apr 26): PF=3.65, WR=43%, Return=+5.1%  [GOOD]
```

**All splits profitable. Smallest PF (1.10) still above breakeven. Best long candidate.**
Note: Only 124 trades in 5 years (low frequency). Bootstrap CI for worst split: PF [0.00, 6.09] — wide but point estimate is positive.

---

## Part 3: Short Strategy Results

### SOLUSDT SHORT — NOT ROBUST (only 2/5 profitable)

```
Full sample: 141 trades, PF=0.97, WR=39.7%, Return=-8.6%
Split 1: PF=0.38 [BAD]    Split 2: PF=0.15 [BAD]    Split 3: PF=0.10 [BAD]
Split 4: PF=2.57 [GREAT]  Split 5: PF=2.14 [GREAT]
```

**3 of 5 splits are unprofitable.** The short edge only works in specific downtrend regimes with momentum. **Not deployable as a standalone strategy.** Full-sample PF=0.97 (sub-1.0) is itself a red flag.

### WLDUSDT SHORT — Weak (1/2 profitable)

```
Full sample: 59 trades, PF=1.57, WR=40.7%, Return=+36%
Split 3: PF=0.30 [BAD]  Split 4: PF=1.53 [OK]
```

Only 2 splits (limited data). Insufficient evidence. **Not deployable.**

### TAOUSDT SHORT — Insufficient Data

```
Full sample: 41 trades, PF=1.02, WR=39.0%, Return=-0.8%
Walk-forward: insufficient data for splits
```

PF=1.02 is essentially breakeven. Only 41 trades in full sample. **Not deployable.**

---

## Part 4: Portfolio Assessment

### Honest Portfolio (only validated edges):

| Strategy | Split 1 | Split 2 | Split 3 | Split 4 | Split 5 | Avg |
|----------|---------|---------|---------|---------|---------|-----|
| LINK long | n/a | +0.5% | +11.5% | +7.2% | +5.1% | +6.1% |
| AVAX long | -2.1% | +11.8% | +4.8% | +5.6% | +3.4% | +4.7% |

**Equal-weight portfolio (2 strategies, 1x):**
- Consistent in 9/10 split-strategy combinations
- Average return per ~3.5 month window: ~5.4%
- Annualized at 1x: ~23% (vs 211% claimed in IG88079)

### Comparison to IG88079 Claims

| Metric | IG88079 Claim | Walk-Forward Reality |
|--------|--------------|---------------------|
| Strategies | 9 long + 5 short | 2 long |
| Ann return (1x) | 211% | ~23% |
| Portfolio size | 14 strategies | 2 strategies |
| Walk-forward | "Confirmed" | Most strategies fail |

**The gap between claims and reality is significant.** IG88079's walk-forward was too lenient or used different parameters.

---

## Part 5: Why Most Edges Fail Walk-Forward

### Regime Analysis

Examining the profitable vs unprofitable windows for ETH and SOL:

| Window | PF | Trend | Vol | Autocorr | Above SMA100 |
|--------|-----|-------|-----|----------|-------------|
| ETH BEST (PF=9.71) | GREAT | -30% | 85% | +0.014 | 47% |
| ETH WORST (PF=0.23) | BAD | -44% | 65% | +0.029 | 47% |
| SOL BEST (PF=2.57) | GREAT | -63% | 77% | +0.038 | 40% |
| SOL WORST (PF=0.10) | BAD | +29% | 73% | -0.007 | 49% |

**Key insight: Volatility is the differentiator, not trend direction.**
- ETH's best split: 85% annualized vol
- ETH's worst split: 65% annualized vol
- ATR Breakout needs HIGH VOLATILITY to generate winners that exceed trailing stop losses on bounces

**The SMA100 regime filter (direction-based) is insufficient.** We need:
1. **Volatility regime filter** — only trade when ATR% > threshold
2. **Trend strength filter** — ADX or similar, not just price vs SMA
3. **Autocorrelation filter** — momentum vs mean-reversion detection

---

## Part 6: Action Items

### Immediate (this session)

1. **Update paper trader to LINK + AVAX only** — the two validated strategies
2. **Kill the cron running 14 strategies** — most are unvalidated
3. **Build ATR Breakout v2 with volatility regime filter**

### Phase 2 (next session)

4. **ATR Breakout v2:** Add ATR% percentile filter (only trade when ATR% in top 40% of rolling 500-bar window)
5. **Test ADX filter** as alternative/addition to SMA100
6. **Re-run walk-forward** on v2 across all 7 pairs
7. **30m timeframe native test** — resampled data showed +31-37% PF improvement for ETH/AVAX

### Phase 3 (when v2 validated)

8. **SOL short regime-adaptive** — only short in high-vol downtrends with momentum
9. **Multi-timeframe confirmation** — higher TF trend alignment
10. **Jupiter perps deployment** — first live capital

---

## Appendix: Data Notes

- **Truncated files (1000 bars):** DOT_USDT, MATIC_USDT, ALGO_USDT, UNI_USDT, DOGEUSDT. These contain the known data bug from 2026-04-16. Need re-download before testing.
- **Daily-only (no 60m):** RENDER, BONK, ORDI. Cannot validate intraday strategies.
- **TAO:** Only has 1h data (17K bars) — sufficient for backtest but not 5-split walk-forward.

---

## Confidence Levels

| Claim | Confidence |
|-------|-----------|
| LINK long has a real edge | HIGH (4/4 splits profitable, PF 1.10-22.31) |
| AVAX long has a real edge | MODERATE-HIGH (4/5 splits, 1 early bad split) |
| ETH long has a real edge | MODERATE (4/5 splits but most recent is PF 0.23) |
| NEAR long has a real edge | LOW (2/3 splits unprofitable) |
| Any short strategy has a real edge | LOW (all fail walk-forward) |
| Volatility regime filter will improve robustness | MODERATE (evidence supports but untested) |

---

**Next doc:** IG88081 (ATR Breakout v2 with volatility regime filter — after testing)
