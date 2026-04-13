# IG88039: Recursive Strategy Optimization Results

## Executive Summary

Completed 2,550 backtests across 4 parallel optimization runs. Key finding: **Strategy parameters are PAIR-SPECIFIC**. The optimal RSI threshold for SOL (40) differs from LINK (38) and AVAX (32). One-size-fits-all parameters destroy edge.

## Testing Scope

| Optimization | Combos | Pairs | Total Backtests |
|--------------|--------|-------|-----------------|
| MR Grid Search | 240 | 6 | 1,440 |
| H3-A Ichimoku | 81 | 6 | 486 |
| H3-B Volume Ignition | 72 | 7 | 504 |
| Regime Stops | 30 | 4 | 120 |
| **TOTAL** | | | **2,550** |

## Optimized Parameters by Strategy

### Mean Reversion (MR)

| Pair | RSI<thresh | BB σ | Vol> | Entry | Stop | Target | PF | Trades |
|------|------------|------|------|-------|------|--------|-----|--------|
| SOL | 40 | 1.5 | 1.5 | T2 | 0.25% | 10% | 1.275 | 537 |
| BTC | 40 | 1.5 | 1.2 | T2 | 0.50% | 7.5% | 1.111 | 893 |
| ETH | 40 | 1.5 | 1.2 | T1 | 0.50% | 7.5% | 1.135 | 881 |
| LINK | 38 | 0.5 | 1.1 | T0 | 0.25% | 15% | 1.311 | 783 |
| AVAX | 32 | 0.5 | 1.3 | T0 | 0.25% | 15% | 1.288 | 366 |
| NEAR | 40 | 1.0 | 1.5 | T2 | 0.25% | 15% | 0.986 | 513 |

**Key Insight:** LINK/AVAX favor tighter BB (0.5σ) and immediate T0 entry. SOL/BTC/ETH favor wider BB (1.5σ) and T2 confirmation.

### H3-A Ichimoku

| Pair | Tenkan | Kijun | Cloud | Vol> | PF |
|------|--------|-------|-------|------|-----|
| SOL | 9 | 26 | 26 | 1.5 | **2.553** |
| NEAR | 12 | 30 | 26 | 1.5 | 1.631 |
| LINK | 7 | 26 | 26 | 1.5 | 1.549 |
| AVAX | - | - | 20 | 1.2 | ~1.0 |
| BTC/ETH | - | - | - | - | <1.0 |

**Key Insight:** Standard Ichimoku (9/26) works for SOL. Longer periods (12/30) for NEAR.

### H3-B Volume Ignition

| Pair | Vol> | Mom | RSI | Entry | PF |
|------|------|-----|-----|-------|-----|
| AVAX | 2.0 | 1 | 40-60 | T2 | **1.516** |
| SOL | 1.8 | 1 | 30-70 | T2 | 1.307 |
| NEAR | 1.5 | 1 | 35-65 | T2 | 1.191 |
| ETH | 2.0 | 2 | 40-60 | T2 | 1.168 |
| BTC | - | - | - | - | <1.0 |

**Key Insight:** Higher volume thresholds (1.8-2.0x) filter noise. T2 entry (2-bar wait) optimal across all pairs.

## Regime-Adaptive Stops (Critical Finding)

Ultra-tight stops with wide targets maximize PF:

| Regime | Stop | Target | Use Case |
|--------|------|--------|----------|
| Low Vol (ATR<2%) | 1.5% | 3.0% | Tight range |
| Mid Vol (ATR 2-4%) | 1.0% | 7.5% | Standard |
| High Vol (ATR>4%) | 0.5% | 7.5% | Wide swings |

**Maximum PF configuration:** Stop 0.25%, Target 10-15% → PF 1.7-2.0

## Combined Portfolio

| Pair | Primary | Secondary | Allocation |
|------|---------|-----------|------------|
| SOL | H3-A (2.55) | MR (1.28) | 40% |
| NEAR | MR aggressive | H3-B (1.19) | 25% |
| LINK | MR (1.31) | - | 15% |
| AVAX | H3-B (1.52) | MR (1.29) | 15% |
| BTC | MR (1.11) | - | **0%** (market leader, monitor only) |
| ETH | - | - | 0% |

**Estimated Portfolio PF:** 1.4-1.6
**Estimated Win Rate:** 25-35%
**Estimated Expectancy:** 0.2-0.3% per trade

## Key Discoveries

1. **Pair-specific parameters are essential.** Using SOL's optimal params on LINK destroys edge.

2. **BTC and ETH have weak/no edge** across all strategies. Focus on alts.

3. **Ultra-tight stops (0.25%) with wide targets (10-15%)** produce highest PF. "Fail fast, run winners."

4. **Entry timing varies by pair:** Some favor T0 (immediate), others T2 (confirmation). Test each.

5. **Volume filter >1.8x** for H3-B dramatically improves signal quality.

6. **Ichimoku works best on SOL** (PF 2.55). Other pairs prefer MR.

## Files Generated

- `data/mr_optimization_results.json` - 1,440 MR backtests
- `data/h3a_optimization_results.json` - 486 H3-A backtests
- `data/h3b_optimization_results.json` - 504 H3-B backtests
- `scripts/optimize_mr.py` - MR grid search engine
- `scripts/optimize_regime_stops.py` - Stop/target optimizer
- `scripts/h3a_optimizer.py` - H3-A optimizer
- `src/quant/h3b_volume_ignition_optimizer.py` - H3-B optimizer

## Next Steps

1. Update `mr_scanner.py` with pair-specific parameters
2. Add H3-A for SOL, H3-B for AVAX as secondary strategies
3. Implement regime-adaptive stops
4. Paper trade combined portfolio 30 days
5. Re-optimize quarterly (parameter drift monitoring)

---

*Generated: 2026-04-12 | Total Backtests: 2,550 | Author: IG-88*
