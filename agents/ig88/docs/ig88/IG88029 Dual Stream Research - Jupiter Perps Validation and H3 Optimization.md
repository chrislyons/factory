# IG88029 Dual Stream Research — Jupiter Perps Validation and H3 Optimization

**Date:** 2026-04-12
**Status:** Complete
**Author:** IG-88

## Executive Summary

Two parallel research streams completed:
1. **Jupiter Perps H3 Integration** — Successfully validated H3-A and H3-B on SOL-PERP
2. **Research Actions** — H3-C optimization, cross-asset validation, 2h timeframe test

**Key Outcome:** Jupiter Perps is now a VALIDATED venue for H3-A and H3-B strategies.

---

## Stream 1: Jupiter Perps H3 Integration

### Methodology
- Ported all H3 signals (A, B, C, D) to SOL-PERP
- Proper perps fee model: 0.07% open + 0.07% close + hourly borrow fee
- Tested at 3x and 5x leverage with ATR trailing stop (2x ATR)
- OOS validation with 70/30 train/test split

### Results

| Strategy | Leverage | OOS PF | Win Rate | Trades | Edge Decay | Candidate |
|----------|----------|--------|----------|--------|------------|-----------|
| H3-A | 3x | **2.073** | 52.4% | 21 | -9.2% | **YES** |
| H3-A | 5x | **2.073** | 52.4% | 21 | -9.2% | **YES** |
| H3-B | 3x | **2.237** | 52.6% | 38 | -6.3% | **YES** |
| H3-B | 5x | **2.237** | 52.6% | 38 | -6.3% | **YES** |
| H3-C | 3x | 0.887 | 37.5% | 80 | -6.5% | NO |
| H3-C | 5x | 0.887 | 37.5% | 80 | -6.5% | NO |
| H3-D | 3x | 0.716 | 37.5% | 88 | -6.9% | NO |
| H3-D | 5x | 0.716 | 37.5% | 88 | -6.9% | NO |

### Key Findings
- **H3-B is the strongest perps candidate**: PF=2.237, n=38 trades, WR=52.6%
- **Edge decay is minimal** (6-9%) for profitable strategies
- **Leverage scales PnL but not PF** — 3x recommended for lower drawdown
- **H3-C and H3-D are not profitable** on perps (PF < 1.0)

### Perps Recommendation
**H3-B at 3x leverage** is the optimal perps configuration:
- Highest trade count (38)
- Best PF (2.237)
- Lowest edge decay (-6.3%)
- Manageable drawdown ($99 at 3x vs $166 at 5x)

---

## Stream 2: Research Actions

### 2a. H3-C Optimization (SOL 4h)
- Parameter sweep: 180 combinations (RSI 45-55, KAMA 4-14, fast/slow combos)
- **Result:** No promotable strategies found
- **Best OOS PF:** 0.860 (losing strategy)
- **Conclusion:** H3-C (RSI + KAMA) does not produce edge on SOL 4h

### 2b. Cross-Asset Validation (ETH, NEAR, INJ 4h)

| Asset | Strategy | OOS PF | OOS n | p-value | Verdict |
|-------|----------|--------|-------|---------|---------|
| ETH | H3-A | 0.396 | 7 | 1.000 | Fails |
| ETH | H3-B | 1.424 | 28 | 0.087 | Marginal |
| ETH | H3-C | **1.394** | 24 | **0.077** | **Closest** |
| NEAR | H3-A | **1.915** | 18 | 0.118 | n too low |
| NEAR | H3-B | 0.301 | 19 | 0.999 | Fails |
| NEAR | H3-C | 0.602 | 22 | 0.835 | Fails |
| INJ | — | — | — | — | Data not available |

**Key Finding:** No cross-asset candidate meets promotion criteria (PF>2.0, p<0.10, n>=20). SOL 4h remains the only validated asset.

### 2c. 2h Timeframe Test (SOL)

| Strategy | OOS PF | OOS n | p-value | Verdict |
|----------|--------|-------|---------|---------|
| H3-A | 1.054 | 16 | 0.444 | Not profitable OOS |
| H3-B | **1.949** | 38 | **0.036** | **Close but PF<2.0** |
| H3-C | 1.345 | 76 | 0.035 | Significant but PF<2.0 |

**Key Finding:** H3-B on 2h shows promise (PF=1.949, statistically significant) but falls just short of the PF>2.0 threshold. 4h remains the confirmed optimal timeframe.

---

## Timeframe Summary (Complete)

| Timeframe | H3-A | H3-B | H3-C | Optimal? |
|-----------|------|------|------|----------|
| 1h | PF 0.289 (FAIL) | PF 1.333 (marginal) | — | NO |
| 2h | PF 1.054 | **PF 1.949** | PF 1.345 | Marginal |
| **4h** | **PF 7.281** | **PF 2.237** | PF 0.860 | **YES** |
| 1d | — | — | — | Not tested with ATR trail |

---

## Updated Venue Status

| Venue | Status | Active Strategies | Notes |
|-------|--------|-------------------|-------|
| Kraken Spot | **LIVE READY** | H3-A, H3-B | SOL 4h, ATR trailing stop |
| Jupiter Perps | **LIVE READY** | H3-B (primary), H3-A (secondary) | 3x leverage recommended |
| Polymarket | IN PROGRESS | LLM-based | 30% effort allocation |
| Solana DEX | OBSERVATION | None | $200K liquidity threshold |

---

## Files Created

- `scripts/jupiter_perps_h3_backtest.py` — Perps integration backtest
- `data/research/perps/jupiter_perps_h3_results.json` — Full perps results
- `data/research/h3c_optimization/` — H3-C parameter sweep results
- `data/research/cross_asset/` — ETH, NEAR validation results
- `data/research/timeframe_test/SOL_2h_Timeframe_*.json` — 2h timeframe results

## Next Steps

1. **Jupiter Perps Live:** Prepare H3-B @ 3x for paper trading
2. **Paper Trade Accumulation:** Continue toward 100 trades for graduation
3. **H3-D Cross-Asset:** Test on assets with available data
4. **1d Timeframe:** Test H3-A/B on daily bars with ATR trailing exit

## References

- IG88024: H3-A and H3-B Strategy Validation Report
- IG88028: Battle Testing and Infrastructure Hardening
- `fact/strategies.md`: Updated strategy registry
- `fact/trading.md`: Updated venue architecture
