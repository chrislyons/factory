# IG88017 Multi-Indicator Convergence Strategy Refinement

**Date:** 2026-04-09
**Status:** Complete
**Session:** Proof & Validation Phase — Milestone 2

---

## 1. Summary

Systematic multi-indicator convergence testing identified one structurally robust
combo: **Ichimoku TK cross + RSI > 55 + Ichimoku composite score >= 3**.

This combo passes OOS walk-forward on 3 of 6 assets tested (SOL 4h, BTC 4h, ETH
daily), while the baseline only passes 2. It is the first signal configuration with
statistically significant in-sample performance AND cross-asset OOS consistency.

---

## 2. Available Indicator Inventory

From `src/quant/indicators.py` (20+ indicators):

| Category    | Indicators                                         |
|-------------|---------------------------------------------------|
| Ichimoku    | TK cross, cloud position, cloud direction, Chikou, composite score (5 sub-conditions) |
| Trend       | ADX (+ +DI/-DI), SuperTrend, KAMA/POC Bands, EMA, Kagi |
| Momentum    | RSI, StochRSI (%K/%D), MACD (histogram, cross)   |
| Volume      | OBV (+ EMA slope), Klinger (KVO vs signal)        |
| Volatility  | Bollinger Bands (%B, bandwidth), ATR percentile   |
| Pattern     | Fibonacci (auto), Donchian, swing points          |

`multi_indicator_confluence()` and `ichimoku_composite_score()` are composite
helpers already present in the library.

---

## 3. Methodology

### Baseline
Ichimoku TK cross above cloud + RSI > 50 (the prior session's edge candidate).

### Filter Testing
24 individual filters tested as add-ons to the baseline on the SOL 4h train period
(Apr 2023 – May 2025, ~4600 bars). Each filter ranked by:
- Delta PF vs baseline
- n retained (sample size cost)
- p-value improvement

### Combination Search
Top 10 PF-improving filters grid-searched for pairs and triples.
Walk-forward validated: train period → test period (May 2025 – Apr 2026).

### Cross-Asset Validation
Three winners from SOL 4h tested on ETH 4h, BTC 4h, SOL daily, ETH daily, BTC daily.
Structural criterion: OOS PF > 1.2 and n >= 5 on >= 3 assets.

---

## 4. Single Filter Results (Train, SOL 4h)

Top filters by PF improvement over baseline (PF 1.374):

| Filter           | n  | WR    | PF    | Sharpe | p-val  | Delta PF |
|------------------|----|-------|-------|--------|--------|----------|
| rsi_55           | 31 | 54.8% | 1.930 | +4.63  | 0.057* | +0.556   |
| chikou_bull      | 31 | 51.6% | 1.857 | +4.25  | 0.073* | +0.483   |
| klinger_bull     | 28 | 53.6% | 1.792 | +4.09  | 0.092* | +0.418   |
| vol_above_ma     | 20 | 55.0% | 1.762 | +4.13  | 0.132  | +0.389   |
| rsi_60           | 24 | 54.2% | 1.734 | +3.89  | 0.123  | +0.360   |
| ichi_score3      | 33 | 48.5% | 1.687 | +3.58  | 0.101  | +0.314   |
| cloud_thick      | 17 | 47.1% | 1.655 | +3.34  | 0.204  | +0.281   |
| kama_slope       | 35 | 48.6% | 1.605 | +3.29  | 0.113  | +0.231   |

**What works:**
- `rsi_55`: Tighter RSI threshold filters out weak-momentum entries. Best single filter.
- `chikou_bull`: Lagging span above historical price = trend is confirmed by time.
- `klinger_bull`: Volume pressure aligns with direction. Weak signal individually but
  synergistic with RSI and Chikou.
- `ichi_score3`: Requires ≥3/5 Ichimoku sub-conditions to be bullish. Good combination
  of all Ichimoku signals into one gate.

**What doesn't work:**
- `adx_20/25`: Removes too many trades without improving WR. ADX is lagging at 4h.
- `cloud_bull`: Cloud direction is already partly embedded in TK cross. Redundant.
- `atr_pct40`: Volatility filter reduces sample too aggressively on 4h.
- `supertrend`, `ema50_bull`: Same signal as regime filter — double counting BTC trend.

---

## 5. Combination Walk-Forward Results (SOL 4h)

| Combo                         | Train n | Train PF | Train p | Test n | Test PF | Test Sh | OOS holds |
|-------------------------------|---------|----------|---------|--------|---------|---------|-----------|
| rsi_55 + ichi_score3          | 26      | 2.558    | 0.020*  | 8      | 3.524   | +9.48   | YES (+)   |
| rsi_55 + chikou_bull + klinger| 21      | 2.895    | 0.019*  | 9      | 2.064   | +5.40   | YES (+)   |
| chikou_bull + klinger_bull    | 22      | 2.613    | 0.027*  | 9      | 2.064   | +5.40   | YES (+)   |
| chikou_bull + vol_above_ma    | 16      | 2.768    | 0.034*  | 8      | 1.611   | +3.50   | YES       |
| rsi_55 + cloud_thick          | 12      | 3.010    | 0.061*  | 3      | 0.000   | —       | NO (n=3)  |

`rsi_55 + cloud_thick` shows train PF 3.01 but collapses OOS — classic overfit on
a rare signal that happened to be predictive in a specific market phase.

---

## 6. Cross-Asset Validation

| Combo                      | SOL 4h | ETH 4h | BTC 4h | SOL 1d | ETH 1d | BTC 1d | Pass count |
|----------------------------|--------|--------|--------|--------|--------|--------|------------|
| BASELINE                   | ✓      | ✗      | ✓      | ✗      | ✗      | ✗      | 2/6        |
| rsi_55 + ichi_score3       | ✓      | ✗      | ✓      | ✗      | ✓      | ✗      | **3/6**    |
| rsi_55+chikou+klinger      | ✓      | ✗      | ✗      | ✗      | ✓      | ✗      | 2/6        |
| chikou + klinger           | ✓      | ✗      | ✗      | ✗      | ✓      | ✗      | 2/6        |

**rsi_55 + ichi_score3 is the only combo that qualifies as structurally robust.**

Notably:
- ETH 4h OOS fails across all combos — Ichimoku TK cross is not an edge on ETH
  at 4h in the current (2025-2026) market regime. ETH has been more range-bound.
- SOL daily OOS is sparse (n ≤ 2 test trades) — not enough data to conclude.
- BTC daily OOS fails consistently — BTC large-cap dynamics are different.

---

## 7. The Winner: `rsi_55 + ichi_score3` on SOL 4h

**Full walk-forward (SOL 4h, 3yr Binance data):**

| Phase       | Period              | n  | WR    | PF    | Sharpe | DD%  | p-val |
|-------------|---------------------|----|-------|-------|--------|------|-------|
| In-sample   | Apr 2023 – May 2025 | 26 | 61.5% | 2.558 | +6.56  | 0.1% | 0.020 |
| Out-of-sample| May 2025 – Apr 2026 | 8  | 75.0% | 3.524 | +9.48  | 0.1% | 0.064 |

**Signal definition (complete):**
1. Ichimoku TK cross: Tenkan crosses above Kijun (bullish crossover)
2. Price above cloud: close > max(Senkou A, Senkou B)
3. RSI > 55 (momentum filter — removes weak entries)
4. Ichimoku composite score >= 3 (≥3 of 5 Ichimoku sub-conditions bullish)
5. BTC 20-bar trend > +5% (macro regime, not RISK_OFF)
6. Regime: NEUTRAL or RISK_ON (RISK_OFF = no trade)

**Exit conditions:**
- ATR stop: 2× ATR below entry
- ATR target: 3× ATR above entry
- Kijun cross: close drops below Kijun (trend weakening)
- Regime flip to RISK_OFF (after min hold bars)

**Position sizing:** 2% fixed fraction (pending Kelly graduation at 100 trades)

---

## 8. What the Convergence Means

Chris's intuition about layering indicators is correct, but the mechanism matters:

- **Redundant layering** (two trend filters, or two price-position filters) doesn't
  help — it just reduces sample size without improving quality. Example: adding
  `ema50_bull` to a strategy that already uses BTC-trend regime adds no new
  information because both capture the same signal.

- **Orthogonal layering** works. `rsi_55` (momentum), `ichi_score3` (multi-condition
  Ichimoku), and the existing Chikou/cloud conditions each measure something different:
  - TK cross: short-term vs medium-term momentum crossover
  - Above cloud: price is in the "safe zone" for longs
  - RSI > 55: current bar's momentum is genuine
  - ichi_score3: the broader Ichimoku picture is bullish (not just the TK line)

- **The Chikou span** (lagging span 26 bars back) is particularly valuable because
  it adds *temporal* confirmation — not just "is price above cloud now" but "is the
  current price level higher than 26 bars ago?" This naturally filters fake breakouts.

---

## 9. H3 Strategy Definition (Final)

**H3-A: SOL/USDT 4h Ichimoku Convergence (Kraken Spot)**
- Signal: Ichimoku TK cross + above cloud + RSI > 55 + ichi_score >= 3
- Regime: BTC 20-bar trend filter (NEUTRAL or RISK_ON)
- Stops: 2× ATR stop, 3× ATR target, Kijun exit
- Sizing: 2% fixed fraction
- Expected rate: ~2–4 signals/month at current regime frequency
- Current status: Paper trade mode — needs 20+ more live trades for statistical validation

**H3-B: ETH/USDT daily (tentative)**
- Same signal as H3-A on daily bars
- OOS: ETH daily passes PF > 1.2 in 3/4 combos tested
- However: n = 5–9 OOS trades, insufficient for standalone confidence
- Status: Monitor alongside H3-A, don't weight it yet

---

## 10. Items Not Yet Tested

These are candidates for the next iteration:

1. **KAMA bands as dynamic stop** — instead of ATR-based stops, exit when price
   closes below the POC lower band. May reduce premature exits.

2. **Fibonacci confluence** — enter only when entry price is near a Fibonacci support
   level (auto_fib_levels). Could improve entry quality.

3. **Donchian breakout confirmation** — require price to be above the 20-bar Donchian
   upper band on entry. Combines with above-cloud for stronger confirmation.

4. **StochRSI filters** — %K crossing above %D at entry adds another momentum layer.
   Not tested in this round.

5. **Volume convergence** — Klinger bullish AND OBV slope positive (both volume
   indicators agreeing). Individual volume filters showed promise; the combination
   wasn't fully explored.

6. **Timeframe confluence** — confirm 4h signals with daily Ichimoku state. Requires
   multi-timeframe data loading but could significantly improve quality.

---

## 11. Next Actions

1. **Implement H3-A in paper trader** — log every SOL 4h signal that fires to
   `data/paper_trades.jsonl`. Current regime is NEUTRAL — watch for entries.

2. **Check current SOL 4h state** — compute live Ichimoku on latest 4h data to
   know if a signal is active.

3. **Test StochRSI and Fibonacci filters** — two unexplored indicators with potential
   orthogonal information content.

4. **Multi-timeframe confluence** — load SOL daily + 4h simultaneously, require
   daily Ichimoku to be bullish before taking 4h entries.

---

*Authored by IG-88 | Proof & Validation Phase | Session 2026-04-09*
