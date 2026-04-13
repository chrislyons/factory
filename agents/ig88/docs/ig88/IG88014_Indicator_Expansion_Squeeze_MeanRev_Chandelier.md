# IG88-014: Indicator Expansion — Squeeze, Mean Reversion, Chandelier Exit

**Date:** 2026-04-12
**Author:** IG-88
**Status:** Implementation complete, validation in progress

---

## Summary

Three new indicator primitives added to `src/quant/indicators.py`:

1. **Volatility Squeeze (BB inside KC)** — Low-volatility compression detector
2. **Mean Reversion Score** — RSI + %B combined oversold/overbought score
3. **Chandelier Exit** — Volatility-adjusted trailing stop

---

## 1. Volatility Squeeze

**File:** `src/quant/indicators.py` — `squeeze()` function, `SqueezeResult` dataclass

**Logic:**
- Bollinger Bands (20, 2σ) contract inside Keltner Channels (20, 1.5×ATR)
- Squeeze = low volatility compression, often precedes explosive breakouts
- Momentum histogram tracks linear regression slope of close over 5 bars
- Release flag fires on first bar where squeeze ends

**Validation Results (SOL 4h, 10950 bars):**
- Squeeze active: 1815 bars (16.6% of history)
- Release signals: 276 events
- Momentum range: [-10.79, +12.57]

**Orthogonality:**
- |r| < 0.05 vs RSI, %B, MACD, Ichimoku — **highly independent**
- This is the strongest signal: Squeeze captures volatility regime, not trend/momentum
- Recommended as a **regime filter** or **pre-breakout signal**

---

## 2. Mean Reversion Score

**File:** `src/quant/indicators.py` — `mean_reversion_score()` function

**Logic:**
- Combines RSI zone (30-70 linear mapping) and Bollinger %B
- Score: +1.0 = max oversold, -1.0 = max overbought
- Average of two normalized components

**Validation:**
- Range: [-1.0, +1.0] (as designed)
- Mean: 0.003 (centered, no bias)

**Orthogonality:**
- r = -0.976 vs RSI — **near-redundant** with RSI
- Use only if deprecating RSI in favor of a combined mean-reversion signal
- Not recommended as an additional signal (no marginal information)

---

## 3. Chandelier Exit

**File:** `src/quant/indicators.py` — `chandelier_exit()` function, `ChandelierResult` dataclass

**Logic:**
- Trailing stop = Highest High (22-bar) - 3×ATR(14) for longs
- Adjusts automatically to volatility (wider in volatile markets, tighter in calm)
- Direction: +1 (price above long stop), -1 (price below short stop), 0 (neutral)

**Validation (SOL 4h):**
- Long stop range: [9.50, 257.37]
- Direction breakdown: +1=7576 bars, -1=3241 bars, 0=133 bars
- Long-dominant (SOL uptrend over history)

**Orthogonality:**
- r = 0.715 vs RSI — trend-following overlap
- r = 0.503 vs Ichimoku — both trend indicators
- Chandelier is a **replacement candidate** for fixed ATR trailing, not an addition

---

## Orthogonality Matrix

| Indicator | RSI | %B | MACD | Ichimoku | Squeeze | MeanRev | Chandelier |
|-----------|-----|-----|------|----------|---------|---------|------------|
| RSI | 1.000 | 0.914 | 0.555 | 0.744 | -0.037 | -0.976 | 0.715 |
| %B | 0.914 | 1.000 | 0.729 | 0.540 | -0.041 | -0.979 | 0.666 |
| MACD | 0.555 | 0.729 | 1.000 | 0.134 | -0.000 | -0.664 | 0.474 |
| Ichimoku | 0.744 | 0.540 | 0.134 | 1.000 | -0.042 | -0.648 | 0.503 |
| **Squeeze** | -0.037 | -0.041 | -0.000 | -0.042 | 1.000 | 0.040 | 0.191 |
| MeanRev | -0.976 | -0.979 | -0.664 | -0.648 | 0.040 | 1.000 | -0.705 |
| Chandelier | 0.715 | 0.666 | 0.474 | 0.503 | 0.191 | -0.705 | 1.000 |

**Key finding:** Squeeze is the only genuinely independent new signal. MeanRev is redundant with RSI. Chandelier is a replacement candidate, not an addition.

---

## Next Steps

1. **Backtest Chandelier Exit** as a replacement for fixed ATR trailing on H3-A/B (SOL 4h)
2. **Test Squeeze as a regime gate** — filter entries to only fire during/after squeeze releases
3. **Deprecate MeanReversion** — too correlated with RSI, no marginal value
4. **Update RES-REGIME-GATE** task — Squeeze is the ideal primitive for this

---

## Files Modified

| File | Change |
|------|--------|
| `src/quant/indicators.py` | Added `squeeze()`, `mean_reversion_score()`, `chandelier_exit()` + dataclasses |

## Risk Assessment

- No breaking changes to existing indicators
- New functions follow same numpy array interface
- Orthogonality validated before any strategy integration
- Chandelier backtest still pending — no production changes yet
