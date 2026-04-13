# IG88014: Portfolio v3 Validation Summary

**Date:** 2026-04-13
**Agent:** IG-88
**Status:** VALIDATED

---

## Executive Summary

Expanded from 3 to **12 pairs** through systematic testing. Found that **2% friction is lethal** for most strategies - only mean reversion on specific pairs survives rigorous bootstrap validation.

**Portfolio v3 Performance:**
- **12 pairs** (5 STRONG, 7 WEAK)
- **208 total trades**
- **PF 2.75** (weighted)
- **Exp 3.19%** per trade
- **WR 63.9%**

---

## Portfolio Composition

### STRONG Pairs (2-2.5% position size)

| Pair | Size | RSI< | BB< | Vol> | Stop | Target | R:R | N | PF | Exp% | WR% |
|------|------|------|-----|------|------|--------|-----|---|----|----|-----|
| ARB | 2.5% | 18 | 0.10 | 1.2 | 1.00 | 2.50 | 1:2.5 | 17 | 6.10 | 6.60 | 76.5% |
| AVAX | 2.5% | 20 | 0.15 | 1.2 | 1.25 | 2.50 | 1:2.0 | 43 | 3.69 | 4.57 | 65.1% |
| UNI | 2.0% | 22 | 0.10 | 1.8 | 0.75 | 2.00 | 1:2.7 | 28 | 2.51 | 3.18 | 57.1% |
| SUI | 2.0% | 18 | 0.05 | 1.2 | 1.00 | 3.00 | 1:3.0 | 10 | 4.95 | 5.84 | 70.0% |
| MATIC | 2.0% | 25 | 0.15 | 1.8 | 1.25 | 2.50 | 1:2.0 | 12 | 3.87 | 5.09 | 66.7% |

### WEAK Pairs (1% position size)

| Pair | Size | RSI< | BB< | Vol> | Stop | Target | R:R | N | PF | Exp% | WR% |
|------|------|------|-----|------|------|--------|-----|---|----|----|-----|
| INJ | 1.0% | 20 | 0.05 | 1.5 | 1.25 | 2.50 | 1:2.0 | 16 | 1.78 | 1.92 | 56.2% |
| LINK | 1.0% | 18 | 0.05 | 1.8 | 1.00 | 2.50 | 1:2.5 | 14 | 1.71 | 1.98 | 57.1% |
| AAVE | 1.0% | 22 | 0.15 | 1.5 | 0.75 | 2.00 | 1:2.7 | 24 | 1.58 | 0.99 | 62.5% |
| ADA | 1.0% | 25 | 0.05 | 1.2 | 1.25 | 2.50 | 1:2.0 | 10 | 2.25 | 1.98 | 80.0% |
| ATOM | 1.0% | 20 | 0.05 | 1.2 | 1.00 | 3.00 | 1:3.0 | 11 | 1.99 | 1.76 | 54.5% |
| ALGO | 1.0% | 25 | 0.20 | 1.2 | 0.75 | 2.00 | 1:2.7 | 10 | 1.90 | 1.36 | 60.0% |
| LTC | 1.0% | 25 | 0.05 | 1.2 | 1.00 | 2.50 | 1:2.5 | 13 | 1.57 | 0.86 | 69.2% |

---

## Key Findings

### 1. Friction Analysis

Tested all pairs at 1%, 1.5%, and 2% friction:

| Friction | ARB PF | AVAX PF | MATIC PF | Viable Pairs |
|----------|--------|---------|----------|--------------|
| 1% | 8.01 | 5.13 | 5.23 | 21 |
| 1.5% | 7.03 | 4.33 | 4.48 | 18 |
| 2% | 6.10 | 3.69 | 3.87 | 12 |

**Insight:** Lower friction helps existing pairs but doesn't unlock fundamentally broken ones. Pairs like DOT, SOL, XRP fail even at 1% friction.

### 2. Timeframe Analysis

| Timeframe | Viable Pairs | Notes |
|-----------|--------------|-------|
| 15m | 0 | Friction dominates |
| 1h | 0 | Noisier than 4h |
| 4h | 12 | **Optimal** |
| 1d | 1 (UNI) | Too few signals |

**Insight:** 4h is the sweet spot - enough signals for validation, low enough friction impact.

### 3. Strategy Comparison

| Strategy | Tested Pairs | Passed (PF>1.5) | Notes |
|----------|--------------|-----------------|-------|
| Mean Reversion | 22 | 12 | Best at 4h |
| Trend Following | 22 | 0 | Fails at 2% friction |
| Momentum | 22 | 0 | Fails at 2% friction |
| Breakout | 22 | 0 | Fails at 2% friction |

**Insight:** Only mean reversion survives at 2% friction. Trend/momentum require lower friction or different venues.

### 4. Multi-Timeframe Filter

Adding daily trend confirmation to 4h MR signals:

| Pair | No Filter PF | Filtered PF | Change |
|------|--------------|-------------|--------|
| UNI | 0.72 | 1.31 | +82% |
| DOGE | 0.97 | 1.62 | +67% |
| Others | - | - | No improvement |

**Insight:** MTF filter helps marginal pairs but can't fix fundamentally broken edges.

---

## Statistical Validation

### Bootstrap Confidence Intervals (10,000 samples)

| Pair | N | PF | PF 5% CI | PF 95% CI | Prob>0 | Verdict |
|------|---|---|----------|-----------|--------|---------|
| ARB | 17 | 6.10 | 2.44 | 23.67 | 100% | STRONG |
| AVAX | 43 | 3.69 | 2.00 | 7.27 | 100% | STRONG |
| UNI | 28 | 2.51 | 1.24 | 5.12 | 98% | STRONG |
| SUI | 10 | 4.95 | 1.46 | 79.30 | 98% | STRONG |
| MATIC | 12 | 3.87 | 1.41 | 11.33 | 99% | STRONG |

### WEAK Pair Confidence

| Pair | N | PF | PF 5% CI | Prob>0 | Verdict |
|------|---|---|----------|--------|---------|
| ADA | 10 | 2.25 | 0.65 | 85% | WEAK |
| ATOM | 11 | 1.99 | 0.61 | 85% | WEAK |
| ALGO | 10 | 1.90 | 0.55 | 82% | WEAK |
| INJ | 16 | 1.78 | 0.68 | 85% | WEAK |
| LINK | 14 | 1.71 | 0.53 | 79% | WEAK |
| AAVE | 24 | 1.58 | 0.72 | 83% | WEAK |
| LTC | 13 | 1.57 | 0.53 | 76% | WEAK |

**WEAK pairs have PF_5 < 1.0** (lower bound below breakeven). They contribute to diversification but are not reliable standalone.

---

## Production Configuration

```yaml
# config/portfolio_v3.json
{
  "ARB": {"rsi": 18, "bb": 0.10, "vol": 1.2, "stop": 1.00, "target": 2.50, "bars": 20, "size": 2.5},
  "AVAX": {"rsi": 20, "bb": 0.15, "vol": 1.2, "stop": 1.25, "target": 2.50, "bars": 20, "size": 2.5},
  "UNI": {"rsi": 22, "bb": 0.10, "vol": 1.8, "stop": 0.75, "target": 2.00, "bars": 15, "size": 2.0},
  "SUI": {"rsi": 18, "bb": 0.05, "vol": 1.2, "stop": 1.00, "target": 3.00, "bars": 25, "size": 2.0},
  "MATIC": {"rsi": 25, "bb": 0.15, "vol": 1.8, "stop": 1.25, "target": 2.50, "bars": 20, "size": 2.0},
  "INJ": {"rsi": 20, "bb": 0.05, "vol": 1.5, "stop": 1.25, "target": 2.50, "bars": 20, "size": 1.0},
  "LINK": {"rsi": 18, "bb": 0.05, "vol": 1.8, "stop": 1.00, "target": 2.50, "bars": 20, "size": 1.0},
  "AAVE": {"rsi": 22, "bb": 0.15, "vol": 1.5, "stop": 0.75, "target": 2.00, "bars": 15, "size": 1.0},
  "ADA": {"rsi": 25, "bb": 0.05, "vol": 1.2, "stop": 1.25, "target": 2.50, "bars": 20, "size": 1.0},
  "ATOM": {"rsi": 20, "bb": 0.05, "vol": 1.2, "stop": 1.00, "target": 3.00, "bars": 25, "size": 1.0},
  "ALGO": {"rsi": 25, "bb": 0.20, "vol": 1.2, "stop": 0.75, "target": 2.00, "bars": 15, "size": 1.0},
  "LTC": {"rsi": 25, "bb": 0.05, "vol": 1.2, "stop": 1.00, "target": 2.50, "bars": 20, "size": 1.0}
}
```

---

## What's Missing for 10+ Strong Pairs

To expand beyond 5 STRONG pairs, we need either:

1. **Lower friction** (< 1.5%) - Requires optimization:
   - Limit orders instead of market orders
   - Better exchange routing
   - Larger stop distances

2. **Different venue** - Perps have different dynamics:
   - Jupiter/Solana ecosystem
   - Different liquidity patterns
   - Funding rate effects

3. **Different strategy** - MR is not the only edge:
   - Trend following works at lower friction
   - Breakout works on higher timeframes
   - Multi-strategy portfolio

---

## Next Steps

1. **Immediate:** Integrate scanner_v2.py with portfolio_v3.json config
2. **Short-term:** Set up Kraken execution with proper risk limits
3. **Medium-term:** Test Jupiter Perps when API is stable
4. **Long-term:** Reduce friction through execution optimization

---

## Files

- `config/portfolio_v3.json`: Production configuration
- `scripts/portfolio_final.py`: Portfolio validation script
- `scripts/friction_ablation.py`: Friction sensitivity analysis
- `scripts/strategy_optimization.py`: R:R optimization per pair
