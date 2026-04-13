# IG88015: Kraken Execution Strategy (Canada-Compliant)

**Date:** 2026-04-13
**Agent:** IG-88
**Constraint:** dYdX blocked in Canada. Kraken is primary venue.

---

## Executive Summary

With Kraken as our venue and limit orders to minimize friction, we can build a **15-pair portfolio** targeting **PF 2.5+** and **2-3% expectancy per trade**.

---

## Friction Optimization on Kraken

| Order Type | Fee | Slippage | Total Friction |
|------------|-----|----------|----------------|
| Market Order | 0.26% | ~0.30% | ~1.06% + buffer = **~2.0%** |
| **Limit Order** | 0.16% | ~0.05% | ~0.51% + buffer = **~1.0%** |
| Limit (Tier 2, $100K+ 30d) | 0.10% | ~0.05% | ~0.45% + buffer = **~0.8%** |

**Decision: Always use LIMIT ORDERS.** This single change cuts friction in half.

---

## Portfolio at 1% Friction (Limit Orders)

### STRONG Pairs (2-2.5% size)

| Pair | PF | Exp% | N | Stop | Target | R:R |
|------|----|----|-----|------|--------|-----|
| ARB | 8.01 | 6.60% | 17 | 1.00 | 2.50 | 1:2.5 |
| SUI | 6.62 | 5.84% | 10 | 1.00 | 3.00 | 1:3.0 |
| AVAX | 5.13 | 4.57% | 43 | 1.25 | 2.50 | 1:2.0 |
| MATIC | 5.23 | 5.09% | 12 | 1.25 | 2.50 | 1:2.0 |
| UNI | 3.49 | 3.18% | 28 | 0.75 | 2.00 | 1:2.7 |

### MEDIUM Pairs (1.5% size)

| Pair | PF | Exp% | N | Stop | Target | R:R |
|------|----|----|-----|------|--------|-----|
| DOT | 3.03 | 2.28% | 9 | 1.00 | 2.50 | 1:2.5 |
| ALGO | 3.11 | 1.36% | 10 | 0.75 | 2.00 | 1:2.7 |
| ATOM | 3.09 | 1.76% | 11 | 1.00 | 3.00 | 1:3.0 |
| FIL | 2.05 | 1.42% | 7 | 1.00 | 2.50 | 1:2.5 |

### WEAK Pairs (1% size)

| Pair | PF | Exp% | N | Stop | Target | R:R |
|------|----|----|-----|------|--------|-----|
| ADA | 3.14 | 1.98% | 10 | 1.25 | 2.50 | 1:2.0 |
| INJ | 2.44 | 1.92% | 16 | 1.25 | 2.50 | 1:2.0 |
| LINK | 2.27 | 1.98% | 14 | 1.00 | 2.50 | 1:2.5 |
| LTC | 2.53 | 0.86% | 13 | 1.00 | 2.50 | 1:2.5 |
| AAVE | 2.49 | 0.99% | 24 | 0.75 | 2.00 | 1:2.7 |
| SNX | 1.71 | 0.72% | 5 | 1.00 | 2.50 | 1:2.5 |

**Totals: 15 pairs, PF ~3.5, Exp ~2.5%**

---

## What Doesn't Work

**BTC/ETH Mean Reversion on 4H:** Despite high liquidity, BTC and ETH do NOT work with our MR strategy on 4H timeframe. They trend too much - need different strategy class.

**Implication:** To trade BTC/ETH, we need:
- Trend-following strategy (but needs <0.5% friction)
- Different timeframe (daily has too few signals)
- Different venue (perps with funding rate arbitrage)

---

## Execution Rules for Kraken

### Limit Order Placement
1. **Always use limit orders** - Never market orders
2. **Place at mid-price** - Execute as maker, not taker
3. **Monitor fill rate** - If fills < 80%, adjust to slightly aggressive limit
4. **Cancel after 30 seconds** - If not filled, re-evaluate

### Risk Management
1. **Position size per trade:** 1-2.5% of portfolio
2. **Max concurrent positions:** 5-7
3. **Daily loss limit:** 5% of portfolio
4. **Weekly loss limit:** 10% of portfolio

### Entry Criteria (from config/portfolio_v3.json)
```
RSI < threshold (18-25, pair-specific)
BB% < threshold (0.05-0.20, pair-specific)
Volume > threshold (1.0-1.8x average)
ATR-based stop: 0.75-1.25x ATR
ATR-based target: 2.0-3.0x ATR
Max hold: 15-25 bars (4H)
```

---

## Paper Trading Plan

Before live trading:

1. **Week 1-2:** Paper trade 5 STRONG pairs on Kraken
2. **Week 3-4:** Validate fill rates and actual slippage
3. **Week 5-6:** Add MEDIUM pairs if paper results confirm
4. **Week 7-8:** Add WEAK pairs, full portfolio paper trading
5. **Week 9+:** If paper shows PF > 2.0, begin live with small size

---

## Path to More Pairs

Current: 15 pairs via spot mean reversion.

To reach 20+ pairs:
1. **Different strategy class** - Trend following on longer timeframes
2. **Cross-exchange arbitrage** - Price discrepancies between Kraken/others
3. **Funding rate arbitrage** - If we can access perps via other venues
4. **Multi-timeframe** - Combine 4H MR with 1D trend filter

---

## Files

- `config/portfolio_v3.json`: Current 12-pair config
- `scripts/kraken_friction_analysis.py`: Fee structure analysis
- `scripts/test_failed_pairs.py`: Testing pairs at lower friction
