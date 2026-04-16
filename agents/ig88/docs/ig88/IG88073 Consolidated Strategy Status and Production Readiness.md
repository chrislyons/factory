# IG88073 — Consolidated Strategy Status & Production Readiness

**Date:** 2026-04-16  
**Status:** VALIDATED — ready for paper trading, live deployment pending Hyperliquid credentials  
**Summary:** Full system status after comprehensive overnight validation sprint.

---

## The One Edge: ATR Breakout (Donchian 20)

**Confirmed across 9 LONG + 5 SHORT assets with walk-forward OOS validation.**

### LONG Sleeve (9 Assets, 2x Leverage)

| # | Asset | PF Range | Ann Ret | Max DD | Data | Status |
|---|-------|----------|---------|--------|------|--------|
| 1 | FIL | 2.37–2.74 | ~250%+ | ~44% | 2yr | VALIDATED |
| 2 | SUI | 1.93–2.74 | ~200%+ | ~35% | 2yr | VALIDATED |
| 3 | AVAX | 1.84–2.05 | 127–201% | 45% | 5yr | VALIDATED |
| 4 | NEAR | 1.74–2.24 | 129–341% | 26–58% | 5yr | VALIDATED |
| 5 | RNDR | 1.68–2.28 | ~180%+ | ~40% | 2yr | VALIDATED |
| 6 | WLD | 1.67–2.36 | ~190%+ | ~44% | 2yr | VALIDATED |
| 7 | ETH | 1.88–1.97 | 98–208% | 25–26% | 5yr | VALIDATED |
| 8 | LINK | 1.86–1.97 | 120–228% | 32% | 5yr | VALIDATED |
| 9 | SOL | 1.62–1.89 | 111–164% | 30–45% | 5yr | VALIDATED |

**Excluded:** BTC (PF 1.28–1.68, too weak), OP/ARB/INJ/AAVE (failed walk-forward)

### SHORT Sleeve (5 Assets, Variant B)

Entry: `close < donchian_low(i-1) - atr(i) * 2.5`  
Params: Lookback=10, ATR_mult=2.5, Trail=2.5%, MaxHold=48h

| Asset | Avg OOS PF | Min OOS PF | Status |
|-------|------------|------------|--------|
| ETH | 2.08–2.76 | 2.08 | VALIDATED |
| LINK | 2.93 | 2.32 | VALIDATED |
| AVAX | 2.55 | 2.48 | VALIDATED |
| SOL | 2.15 | 1.88 | VALIDATED |
| SUI | 2.14 | 1.90 | VALIDATED (new) |

**Failed:** NEAR (PF 0.83), BTC (marginal), RNDR/FIL (no trades)

---

## Leverage Analysis

| Level | Expected Return | Max DD | Kelly Alignment |
|-------|----------------|--------|-----------------|
| 1x | 75–150% | 15–25% | Half-Kelly (0.96x) |
| 2x | 150–350% | 26–58% | Full Kelly (1.93x) |
| 3x | 250–525% | 38–84% | Over-Kelly (aggressive) |

**Recommendation:** Start at 2x (Kelly-optimal). Move to 3x only after live DD confirms <25%.

---

## Regime Analysis

ATR BO is profitable in ALL market regimes on ETH:
- **BULL:** PF 2.12, WR 42.5% (best)
- **BEAR:** PF 1.52, WR 38.6% (still profitable)
- **SIDEWAYS:** PF 1.60, WR 35.1% (still profitable)

BULL filter improves walk-forward PF on all 5 tested assets (ETH/AVAX/LINK/NEAR/SOL).

**Decision:** Add BULL regime filter to paper trader for +14% PF improvement.

---

## Correlation Warning

All 10 assets are highly correlated (r=0.62–0.83 on returns). This means:
- Portfolio is essentially one bet on crypto beta, NOT diversified
- Drawdowns will hit all positions simultaneously
- MaxDD estimates from single-asset backtests underestimate portfolio DD
- Position sizing must account for this — reduce per-asset allocation

---

## What We Killed

| Strategy | Reason |
|----------|--------|
| RSI | PF < 1.1 OOS |
| MACD | PF < 1.1 OOS |
| EMA crossover | PF < 1.1 OOS |
| Bollinger Band MR | PF < 1.1 OOS |
| VWAP | PF < 1.1 OOS |
| Session timing | PF < 1.1 OOS |
| Funding arb | Not viable |
| Volume+ADX filter | Doesn't generalize (only helps ETH/SUI, hurts 4/6 assets) |
| RSI<70 filter | HURTS all assets (filters out winning breakouts) |
| Basic SHORT (Donchian low) | PF 0.81–0.98 (original SHORT logic was wrong) |

---

## What We Built

| Component | Status | Location |
|-----------|--------|----------|
| Paper trader | RUNNING | scripts/atr_paper_trader.py |
| Cron (4h scan) | ACTIVE | job 06c0ff71c031 |
| Leverage backtest | DONE | scripts/atr_leverage_backtest.py |
| New asset validation | DONE | scripts/atr_new_assets_backtest.py |
| SHORT grid search | DONE | scripts/atr_short_grid_search_v2.py |
| Regime analysis | DONE | scripts/regime_gated_atr_bo.py |
| Kelly optimization | DONE | scripts/kelly_optimization.py |
| Correlation matrix | DONE | scripts/compute_correlation.py |
| Indicator combos | DONE | scripts/combo_test.py |
| Strategy registry v3 | DONE | data/strategy_registry.json |

---

## Next Steps (Priority Order)

1. **Paper trade for 2+ weeks** — collect real signal data, validate PF matches backtests
2. **Hyperliquid deposit + API keys** — from Chris, needed for live deployment
3. **Regime-gated paper trader** — add BULL filter for +14% PF improvement
4. **Live deployment** — after paper trading validates (first trade needs Chris approval)
5. **Monitor and iterate** — track live PF vs backtest PF, adjust if degradation >20%

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| High correlation → simultaneous DD | Max 15% per position, total exposure <100% |
| 2yr data assets may not generalize | Require 5yr validation for capital >$5K |
| Overfitting on SHORT params | Only deploy on assets with 3+ surviving combos |
| Regime change | BULL filter gates entries; strategy profitable in all regimes |
| Leverage liquidation | 2x base, stop at entry-2*ATR limits max loss per trade |

---

## References

[1] IG88071 — Comprehensive System Review and Strategy Roadmap  
[2] IG88072 — Expanded Asset Universe & Portfolio Optimization
