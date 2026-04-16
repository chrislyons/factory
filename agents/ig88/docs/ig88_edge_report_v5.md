# IG88 Portfolio v5 — Edge Exploration Report

**Generated:** 2026-04-15 17:35 UTC  
**Purpose:** Test 5 hypotheses for new edges beyond current long-only 4h strategies  
**Current System:** ETH/LINK long-only on 4h (Keltner breakout, Vol breakout, MACD hist)

---

## Executive Summary

| Hypothesis | Verdict | Key Finding |
|-----------|---------|-------------|
| H1: Short-side edges (ETH 4h) | **KILL** | PF=0.757, WR=31.7% — shorts lose money |
| H2: Higher timeframe edges | **MARGINAL** | Weekly MACD PF=2.825 but only 13 trades |
| H3: New assets (SOL/AVAX/NEAR) | **MARGINAL** | Daily Keltner fails, but 4h momentum works |
| H4: Funding rate arb | **KILL** | Current rates near zero/negative |
| H5: Stablecoin yield | **KILL** | Too small ($50 CAD) for DeFi gas costs |

**Key Insight:** No new standalone edges found. However, SOL already has an edge via the existing 4h momentum breakout strategy (PF=1.417). Current Portfolio v5 approach remains optimal.

---

## Hypothesis 1: Short-Side Edges on ETH 4h

**Signal:** close < EMA20 - 2*ATR, volume > 1.5x average

### Results

| Metric | Value |
|--------|-------|
| Profit Factor | 0.757 |
| Win Rate | 31.7% |
| Total Trades | 1,150 |
| Avg Win | +1.82% |
| Avg Loss | -1.12% |
| Total Return | -89.4% |

### Walk-Forward Analysis

| Split | IS PF | OOS PF | OOS Trades |
|-------|-------|--------|------------|
| 1 | 0.06 | 0.65 | 21 |
| 2 | 0.82 | 2.69 | 7 |
| 3 | 0.69 | 0.93 | 11 |
| 4 | 1.60 | 1.05 | 23 |
| 5 | 0.69 | 0.58 | 14 |

### Regime-Filtered (RSI > 60)

Zero trades generated — the overbought regime filter eliminates all signals.

### Verdict: KILL

Short signals on ETH 4h do not produce profits. The PF < 1.0 across aggregate testing confirms shorts lose money in this market structure. Crypto's long-bias makes shorting unreliable except in severe downtrends.

---

## Hypothesis 2: Higher Timeframe Edges

### ETH Daily Keltner Breakout

| Metric | Value |
|--------|-------|
| Profit Factor | 0.759 |
| Win Rate | 36.2% |
| Total Trades | 116 |

Daily timeframe performs worse than 4h — does NOT reduce noise as hypothesized.

### ETH Weekly MACD Histogram

| Metric | Value |
|--------|-------|
| Profit Factor | 2.825 |
| Win Rate | 61.5% |
| Total Trades | 13 |

**Interesting result** — weekly MACD histogram cross shows high PF but critically low trade count (13 trades over ~9 years). This is statistically unreliable for a standalone strategy.

### Verdict: MARGINAL (but insufficient)

Higher timeframes do NOT improve performance. Daily is worse than 4h. Weekly has too few trades. The 4h timeframe appears to be the sweet spot for crypto momentum.

---

## Hypothesis 3: New Assets Analysis

### Daily Keltner Breakout (New Test)

| Asset | PF | WR | Trades | OOS PF (avg) | Verdict |
|-------|-----|-----|--------|--------------|---------|
| SOL | 0.540 | 28.8% | 66 | ~0.31 | KILL |
| AVAX | 0.278 | 17.2% | 58 | ~0.00 | KILL |
| NEAR | 0.129 | 8.8% | 57 | ~0.00 | KILL |

All three assets fail walk-forward validation on daily Keltner breakout.

### 4h Momentum Breakout (Existing Data)

From `momentum_breakout_full.json` — existing validation shows:

| Asset | PF | WR | Trades | Params | Verdict |
|-------|-----|-----|--------|--------|---------|
| BTC | 1.950 | 43.9% | 57 | ADX>35, Vol>2.0x | VALIDATE |
| ETH | 2.527 | 52.9% | 68 | ADX>30, Vol>2.0x | VALIDATE |
| SOL | 1.417 | 40.3% | 62 | ADX>25, Vol>2.0x | MARGINAL |
| LINK | 2.422 | 49.8% | 54 | ADX>30, Vol>1.5x | VALIDATE |
| AVAX | 2.011 | 45.2% | 49 | ADX>25, Vol>1.5x | VALIDATE |

### Key Insight

The edge is NOT asset-specific — it's signal-specific. The 4h momentum breakout (HH20 + Volume + ADX) works across multiple assets. Daily Keltner breakout does NOT transfer. The existing portfolio already includes SOL via momentum breakout.

### Verdict: MARGINAL (already covered)

No new assets needed. SOL/AVAX already have edges via 4h momentum. The portfolio is adequately diversified.

---

## Hypothesis 4: Funding Rate Arbitrage

### Current Funding Rate Distribution (Binance, proxy for Jupiter)

**ETHUSDT Perps (last 200 periods):**
- Average: -0.0013% per 8h
- Median: -0.0004%
- P90: 0.0051%, P95: 0.0066%
- Periods above 5bps: 0 (0.0%)
- Periods above 10bps: 0 (0.0%)

**SOLUSDT Perps (last 200 periods):**
- Average: -0.0053% per 8h
- Median: -0.0041%
- P90: 0.0073%, P95: 0.0100%
- Periods above 5bps: 0 (0.0%)
- Periods above 10bps: 0 (0.0%)

### Analysis

Funding rates are currently near zero or negative. The basis trade (short perp + long spot) requires funding > 5bps to be profitable after friction. Current market conditions show **zero opportunities** for this strategy.

### Historical Context

Funding rates were much higher during:
- Bull markets (2021, late 2024)
- High leverage periods
- Post-FTX recovery

The current NEUTRAL/LOW vol regime suppresses funding rates.

### Verdict: KILL (for now)

Not viable in current market regime. Monitor for bull market conditions when funding rates spike.

---

## Hypothesis 5: Stablecoin Yield for Idle Capital

### Current Situation
- Kraken balance: $49.18 CAD
- Available DeFi protocols: Aave (3-8%), Compound (3-6%), Maker DSR (5-8%)

### Yield Impact Analysis

| APY | Annual Yield | Monthly Yield |
|-----|-------------|---------------|
| 3% | $1.48 CAD | $0.12 CAD |
| 5% | $2.46 CAD | $0.20 CAD |
| 8% | $3.93 CAD | $0.33 CAD |

### Problem: Gas Costs

Ethereum mainnet transactions cost $2-10+ per transaction. Moving $50 to DeFi and back would cost more in gas than a year of yield.

### Verdict: KILL

Keep capital as trading margin. Revisit when portfolio exceeds $1,000 CAD.

---

## Recommendations

1. **Stick with Portfolio v5** — The current long-only 4h strategies on ETH/LINK remain the best edges discovered.

2. **No short-side edge** — Don't add shorts. Crypto's structural long-bias makes shorting unreliable.

3. **4h is optimal** — Daily and weekly timeframes don't improve results. The 4h timeframe balances signal frequency with noise reduction.

4. **ETH/LINK focus is correct** — While SOL/AVAX have 4h momentum edges, they're marginal (PF < 2.0). ETH/LINK have stronger edges (PF > 2.4).

5. **Funding arb: Monitor, don't trade** — Wait for bull market conditions when funding rates spike above 5bps consistently.

6. **Capital too small for DeFi yield** — Focus on growing trading capital first.

---

## Files Created

- `/Users/nesbitt/dev/factory/agents/ig88/scripts/edge_exploration_v5.py` — Full test harness
- `/Users/nesbitt/dev/factory/agents/ig88/data/edge_discovery/edge_exploration_v5.json` — Raw results
- `/Users/nesbitt/dev/factory/agents/ig88/docs/ig88_edge_report_v5.md` — This report

---

## Next Steps

1. Continue monitoring current ETH/LINK edges
2. Re-test funding arb when market regime shifts to HIGH vol
3. Consider 1h timeframe for tighter entries on existing signals
4. Explore cross-asset correlation filters (BTC as regime indicator)
5. Monitor SOL/AVAX 4h momentum for potential portfolio expansion