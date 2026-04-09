# IG88021 Strategy Refinement Sprint: Exits, Perps, and Timeframes

**Date:** 2026-04-09
**Status:** Complete
**Covers:** Parallel research batch resolving 7 open items from IG88020

---

## 1. Summary of Findings

Seven open items from the progress report were resolved in parallel:

| Item | Result |
|------|--------|
| H3-C with ATR trailing exit | **Significant improvement** — OOS PF 2.25→3.86 |
| H3-D cross-asset expansion | Confirmed SOL-specific — daily alts all fail |
| Confidence-weighted sizing | Rejected — score=4 never fires; fixed 2% wins |
| Jupiter Perps fix + modeling | Fixed, viable at 2× (pre-borrow). Borrow ~0.56%/trade at 3× |
| 1h timeframe test | Rejected — H3-A fails, H3-B marginal |
| H3-C on ETH 4h with ATR trail | **New finding — PF 2.31, p=0.049 significant** |
| Data expansion | 2yr 1h for BTC/ETH/SOL fetched (17,500+ bars each) |

---

## 2. H3-C Exit Upgrade: ATR Trailing Stop

**Before (fixed 2×/3× ATR):** OOS PF 2.249, Sharpe +6.09, p=0.038
**After (ATR trailing):** OOS PF 3.856, Sharpe +7.64, p=0.017

Improvement: +71% OOS PF, +25% OOS Sharpe. Same directional pattern as H3-A
and H3-B — the ATR trailing stop universally beats fixed exits across all strategies.

**H3-C now uses ATR trailing stop.** This is the final exit for all four strategies.

**H3-C on ETH 4h (new):** OOS PF 2.309, Sharpe +5.81, p=0.049, n=22.

H3-C now has two confirmed cross-asset OOS results:
- SOL/USDT 4h: PF 3.856, p=0.017
- ETH/USDT 4h: PF 2.309, p=0.049

BTC 4h (PF 0.90) and alts (NEAR, AVAX) fail. H3-C is a SOL+ETH 4h signal.

---

## 3. Confidence-Weighted Sizing: Rejected

**Hypothesis:** Scale position size by Ichimoku composite score.
- Score=3 → 2% of wallet
- Score=4 → 3%
- Score=5 → 4%

**Finding:** Score=4 never fires at H3-A entry bars. The scoring distribution at
valid H3-A entries is bimodal: 65% score=3, 35% score=5. Score=4 is structurally
absent — the conditions that generate a TK cross above cloud with RSI>55 naturally
skip score=4 and jump directly to 5.

This makes the 3-tier scheme degenerate into 2-tier (2% vs 4%). The extra 4% at
score=5 entries slightly hurts OOS PnL (-0.19%) and increases max drawdown.

**Decision: fixed 2% per signal across all strategies.** Score-based sizing
adds complexity without OOS benefit due to the bimodal distribution.

---

## 4. H3-D Cross-Asset Expansion: Confirmed SOL-Specific

Tested OBV EMA10 cross + RSI cross on ETH/NEAR/LINK/AVAX daily:

| Asset | OOS n | OOS PF | p | Verdict |
|-------|-------|--------|---|---------|
| ETH daily | 11 | 0.936 | 0.538 | No edge |
| NEAR daily | 4 | 0.625 | 0.631 | Too few trades |
| LINK daily | 7 | 0.624 | 0.704 | No edge |
| AVAX daily | 6 | 0.404 | 0.824 | No edge |

Root cause: simultaneous OBV+RSI cross on daily bars is too rare and too
asset-specific. The signal fires ~1-2×/month on daily — ETH in-sample PF 2.46
(p=0.043) completely fails OOS. Classic single-period overfit.

**H3-D remains valid on SOL 4h only** (OOS PF 3.92, p=0.003). It adds n=9 to
the combined portfolio (31 total with H3-A+B+D vs 22 with H3-A+B) but dilutes PF
from 7.28 to 3.78. Primary portfolio stays H3-A+B.

---

## 5. Jupiter Perps — Corrected Simulation

**Bug:** The prior implementation divided ATR by leverage, making stops impossibly
tight. Corrected approach: run standard ATR stops in price terms, post-scale PnL.

**Fee structure (important):**
- Spot (Kraken): 0.16%/side = 0.32% round trip
- Perps (Jupiter): 0.07%/side = 0.14% round trip
- **Perps are cheaper than spot by 0.18%**

| Leverage | OOS n | WR | PF | MaxDD | Note |
|----------|-------|-----|-----|-------|------|
| 1× | 16 | 68.8% | 7.043 | 5.6% | Fee-adjusted baseline |
| 2× | 16 | 68.8% | 6.580 | 11.6% | **Recommended** |
| 3× | 16 | 68.8% | 6.436 | 17.7% | Viable, within risk limits |
| 5× | 16 | 68.8% | 6.324 | 29.9% | Too high MaxDD |

All leverage levels p=0.001. PF decreases slightly with leverage due to PnL
volatility scaling while the fee saving is fixed.

**Borrow fee analysis:**
- Average hold duration: 37.3 hours (median 28h, max 80h)
- At 0.005%/hr (typical Jupiter utilization), 3× leverage costs **0.56% per trade**
- At 0.001%/hr (low utilization), cost drops to **0.11% per trade**
- Our trades are large enough (avg winner well above 1%) that borrow fees don't
  eliminate the edge, but they do compress it

**Recommendation for live deployment:** 2× leverage. MaxDD stays under 12%,
borrow fees manageable at 0.37% per trade (vs 0.56% at 3×). Monitor actual
Jupiter borrow rates and adjust position sizing if rates spike.

---

## 6. Timeframe Analysis: 4h is Optimal

Tested H3-A and H3-B on SOL/USDT 1h (17,517 bars, 2yr history):

| Strategy | Timeframe | OOS n | OOS PF | p | Verdict |
|----------|-----------|-------|--------|---|---------|
| H3-A | 4h | 8 | 5.556 | 0.011 | Primary |
| H3-A | 1h | 23 | 0.289 | 0.996 | **Fails** |
| H3-B | 4h | 16 | 6.162 | 0.001 | Primary |
| H3-B | 1h | 43 | 1.333 | 0.209 | Marginal |

More bars (n=23/43 at 1h vs n=8/16 at 4h) doesn't help — quality collapses.

H3-A on 1h: OOS PF 0.289 is a definitive loss. The Ichimoku cloud at 1h is too
noisy — Tenkan and Kijun cross constantly on short time structures, generating
many false signals that pass all filter conditions but don't hold.

H3-B on 1h: OOS PF 1.333, p=0.209 — marginally positive but not significant.
Volume spikes on 1h are more common (daily noise) and less predictive than the
rarer, higher-conviction spikes on 4h.

**4h is the confirmed optimal timeframe. Do not deploy to 1h.**

---

## 7. Updated Data Inventory

New files fetched:

| File | Bars | Coverage |
|------|------|----------|
| binance_BTC_USD_60m.parquet | 17,517 | Apr 2024 – Apr 2026 |
| binance_ETH_USDT_60m.parquet | 17,520 | Apr 2024 – Apr 2026 |
| binance_SOL_USDT_60m.parquet | 17,517 | Apr 2024 – Apr 2026 |

Total data on disk: 30 parquet files covering 27 symbols across 4 timeframes.

---

## 8. Revised Strategy Specifications

### H3-A (unchanged signal, unchanged exit)
SOL/USDT 4h. Ichimoku TK + above cloud + RSI>55 + score>=3. ATR trail.

### H3-B (unchanged signal, unchanged exit)
SOL/USDT 4h. Vol>1.5× + RSI cross 50. ATR trail.

### H3-C (exit upgraded, cross-asset expanded)
SOL/USDT 4h + ETH/USDT 4h. RSI cross 52 + KAMA(4) cross. **ATR trail (upgraded).**

### H3-D (unchanged, SOL-specific confirmed)
SOL/USDT 4h. OBV>EMA(10) + RSI cross 50. ATR trail.

### Combined H3-A+B Portfolio
Primary. SOL/USDT 4h. OOS PF 7.28, Z=7.73, p<0.01 vs permutation null.

### Jupiter Perps (H3-B signal)
SOL-PERP, 2× leverage recommended. OOS PF ~6.58 pre-borrow fees.
Borrow ~0.37% per trade at 2×. Net OOS edge remains positive.
Not yet deployed — requires live Jupiter account and borrow rate monitoring.

---

## 9. Open Items (Remaining)

1. **H1 Polymarket** — EVM/Polygon wallet. Highest expected value venue. Blocked.
2. **Kraken spot account** — Required for live H3-A/B/C deployment.
3. **Jupiter account + SOL funding** — Required for perps deployment.
4. **Borrow rate live monitoring** — Before perps deployment, need real-time rate feed.
5. **H3-C ATR trail on NEAR/LINK 4h** — New 4h data now available; quick test.
6. **100 paper trades** — graduation threshold for live deployment.

---

*Authored by IG-88 | Proof & Validation Phase | 2026-04-09*
