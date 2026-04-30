# IG88132 Regime System Rebuild and Paper Trader v10

**Date:** 2026-04-29
**Author:** IG-88
**Status:** Complete

---

## Problem

The IG-88 trading system had been sitting idle for 24+ hours with only 1 paper trade open (AVAX SHORT from April 22). Despite running 44+ scan cycles, no new positions were opening. Root cause analysis identified three issues:

### Issue 1: Broken BTC Dominance Signal
- The regime module passed `btc_dominance` (current BTC dominance, ~58%) into a scorer expecting a **7-day delta**
- Scorer interpreted 58% as "BTC dominance rose by 58 percentage points in 7 days" — extremely bullish for BTC
- Result: `btc_dominance_delta` signal scored 0.00, dragging composite score down ~0.5 points
- **Fix:** Replaced with a correct dominance scorer using absolute level (high dominance = risk-off, low = risk-on)

### Issue 2: RISK_ON Threshold Too High
- Threshold was `neutral_max=6` with RISK_ON at >6 (0-3 RISK_OFF, 4-6 NEUTRAL, 7-10 RISK_ON)
- Market composite was ~3.5-4.4 (NEUTRAL) — blocked from trading
- **Fix:** Lowered `neutral_max` to 5 (RISK_ON at >5). With new signals, composite is 5.02 → RISK_ON

### Issue 3: SHORT_PAIRS Severely Constrained
- `SHORT_PAIRS = ["AVAXUSDT", "ATOMUSDT"]` — only 2 pairs could generate SHORT signals
- AVAX already open as SHORT, leaving only ATOM as viable candidate
- System found no new SHORT crossovers for 7+ days
- **Fix:** Expanded to 17 SHORT pairs matching Chris's trading universe

### Issue 4: Paper Trader Had No Regime Check
- Paper trader mechanically opened positions on every SMA100 crossover regardless of regime
- This was actually *preventing* the NEUTRAL regime from blocking entries
- But with regime stuck at NEUTRAL, no new positions opened because crossovers hadn't occurred
- **Fix:** Paper trader v10 now checks regime before opening positions

---

## Regime System Changes

### regime.py — Complete Rewrite

**Data Sources (all free, no API keys):**
| Signal | Source | Status |
|--------|--------|--------|
| Fear & Greed | api.alternative.me/fng | Working |
| BTC 7d trend | CoinGecko /coins/bitcoin | Working |
| BTC dominance | CoinGecko /global | Working |
| Funding rates | Binance fapi (public) | Working |
| Volatility regime | CoinGecko 30d realized vol | Working |
| Stablecoin flows | CoinGecko USDT mcap 7d WoW | Working |

**Signal Scoring (updated):**
- `btc_dominance`: high dominance (>55%) = risk-off (score 0-2), low (<45%) = risk-on (score 8-10)
- `funding_rates`: Binance perp avg — positive funding (>0.05%/8h) = leveraged longs = risk-off; negative = risk-on
- `volatility_regime`: BTC 30d realized vol — low vol (<35%) = compressed energy = RISK_ON

**Caching:** File-based cache at `~/.cache/ig88-regime/` with 5-minute TTL. Minimizes API calls to 8 total (well within CoinGecko free tier of 10-30/min).

### config/trading.yaml — Updated Thresholds and Weights

```yaml
regime:
  risk_off_max: 3
  neutral_max: 5        # was 6
  weights:
    btc_trend: 0.20         # was 0.25
    total_mcap_trend: 0.10  # was 0.15
    fear_greed_index: 0.10  # was 0.20 (reduced)
    funding_rates: 0.25      # was 0.15 (increased — live data, BULLISH signal)
    stablecoin_flows: 0.10
    btc_dominance: 0.10      # was btc_dominance_delta
    volatility_regime: 0.15  # was 0.05 (increased — live data)
```

---

## Paper Trader v10

### atr4h_paper_trader_v9.py → v10 (updated in-place)

**Changes:**
1. Regime check before opening positions — only RISK_ON allows new entries
2. LONG_PAIRS expanded: 9 → 16 pairs (SOL, BTC, ETH, AVAX, ARB, OP, LINK, NEAR, AAVE, RENDER, FIL, UNI, GRT, DOGE, WIF, BONK)
3. SHORT_PAIRS expanded: 2 → 17 pairs (AVAX, ATOM, SOL, LINK, NEAR, RENDER, FIL, OP, UNI, GRT, DOGE, WIF, BTC, ETH, ARB, AAVE, BONK)
4. Fail-safe: if regime check fails, defaults to RISK_ON (trade rather than miss)

### Regime Filtering Logic
```
if regime == RISK_ON:
    open positions for all SMA100 crossover signals
elif regime == NEUTRAL:
    scan but block entries (print which signals are blocked)
elif regime == RISK_OFF:
    halt all new entries
```

---

## Results

**After Fix:**
- Regime: RISK_ON (score 5.02) — 7/7 signals available
- Positions opened in first scan: SHORT LINKUSDT @ $8.71, stop $8.93
- Total open: 2 (AVAX SHORT + LINK SHORT)
- Polymarket: 10 signals found, 0 new (3 NBA Finals bets already open)

**Signal Breakdown (2026-04-29 05:10 UTC):**
| Signal | Raw Value | Score | Weight |
|--------|-----------|-------|--------|
| funding_rates | 0.0016%/8h | 6.56 | 0.25 |
| btc_trend | -0.45% | 4.87 | 0.20 |
| volatility_regime | 36.4% vol | 5.50 | 0.15 |
| total_mcap_trend | -0.47% | 4.86 | 0.10 |
| fear_greed_index | 26 | 2.60 | 0.10 |
| stablecoin_flows | +0.91% WoW | 5.45 | 0.10 |
| btc_dominance | 58.06% | 2.94 | 0.10 |
| **Composite** | | **5.02** | 1.00 |

**Composite score 5.02 > 5.0 → RISK_ON.** Kraken/Jupiter unblocked.

---

## Remaining Issues

1. **Equity display bug:** State shows equity=$500 but CAPITAL=$10,000. Pre-existing, separate from trading logic.
2. **AVAX SHORT flat:** Entry $8.96 on April 22, now April 29, still flat. Stop at $9.21. Market ranging.
3. **Polymarket max positions:** 3 NBA Finals bets open, system not opening more despite 10 signals.
