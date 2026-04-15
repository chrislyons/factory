# IG88059 Portfolio v4 — Keltner Alpha + 3-Edge System

**Date:** 2026-04-28
**Status:** VALIDATED — Ready for paper trading deployment
**Previous:** IG88054 (Portfolio v2, superseded)

---

## Portfolio Composition

Portfolio v4 drops the marginal ETH Momentum Asia edge (PF 1.28 at 50% walk-forward) and replaces it with the Thursday/Friday Keltner alpha.

| # | Edge | Allocation | Leverage | Trailing Stop |
|---|------|-----------|----------|---------------|
| 1 | ETH Vol Breakout 4h | 40% | 2× | 4.0×ATR |
| 2 | ETH Thu/Fri Keltner | 40% | 2× | 3.0×ATR |
| 3 | LINK Thu/Fri Keltner | 20% | 1.5× | 3.0×ATR |

## Edge Specifications

### Edge 1: ETH Vol Breakout 4h
- **Entry:** ATR > 1.5×SMA(50) AND close > SMA(20) AND volume > 1.5×SMA(20)
- **Exit:** 4.0×ATR trailing stop (from IG88054 optimization)
- **OOS PF:** 3.54 | WR 46% | n=41 | Avg +5.67%

### Edge 2: ETH Thu/Fri Keltner Breakout
- **Entry:** day ∈ {Thu, Fri} AND close > EMA(20) + 2×ATR(14) AND volume > 1.5×SMA(20) AND ADX(14) > 25
- **Exit:** 3.0×ATR trailing stop
- **OOS PF:** 10.9 | WR 68% | n=34 | Avg +10.54%

### Edge 3: LINK Thu/Fri Keltner Breakout
- **Entry:** day ∈ {Thu, Fri} AND close > EMA(20) + 2×ATR(14) AND volume > 1.5×SMA(20)
- **Exit:** 3.0×ATR trailing stop
- **OOS PF:** 2.41 | WR 53% | n=53 | Avg +2.27%

## Monte Carlo Projection (5,000 paths, 2× leverage)

| Metric | Value |
|--------|-------|
| Median return | 3.59× per year |
| Mean return | 4.03× per year |
| P(≥2×) | 92.5% |
| P(≥3×) | 65.5% |
| P(≥5×) | 23.8% |
| P(≥10×) | 1.4% |
| P(loss) | 0.0% |
| 5th percentile | 1.85× |
| 95th percentile | 7.6× |

## Risk Profile

- **Maximum single-trade loss:** -11.1% (ETH Vol Breakout worst case)
- **Expected trades per year:** ~40-50 across all edges
- **Correlation:** ETH edges are correlated (same asset), LINK provides partial diversification
- **2023 risk:** ETH Thu/Fri Keltner produced PF 0.38 in 2023 (low-vol regime). ATR percentile filter could mitigate.

## Comparison to Previous Portfolios

| Portfolio | Median | P(≥2×) | P(loss) | Edges |
|-----------|--------|--------|---------|-------|
| v1 (MR 4h) | 1.7× | 38% | 5.7% | 1 |
| v2 (Mom+Vol) | 4.3× | 95% | 0.0% | 2 |
| **v4 (Keltner+3)** | **3.6×** | **92.5%** | **0.0%** | **3** |

v4 has slightly lower median than v2 but includes the Keltner alpha (which has much higher PF per trade) and drops the fragile Momentum Asia edge.

## Deployment Plan

1. Update `paper_trader_v2.py` with Portfolio v4 logic
2. Run paper trading for minimum 30 days / 10+ trades
3. Deploy to Kraken with $500 per edge (within auto-execute threshold)
4. Scale allocation after 3-month live validation
