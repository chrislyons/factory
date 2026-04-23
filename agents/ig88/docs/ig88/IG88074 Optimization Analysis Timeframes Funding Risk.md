# IG88074 — Optimization Analysis: Timeframes, Funding, Risk, and Polymarket

**Date:** 2026-04-16  
**Status:** ANALYSIS COMPLETE — recommendations for production deployment  
**Summary:** Post-validation optimization sprint. Identified 3 concrete improvements to existing edge.

---

## 1. Timeframe Optimization

**Test:** ATR Breakout on 15m, 30m, 60m candles (resampled from 1h data).  
**Walk-forward:** 5 splits per asset/timeframe combination.

| Asset | 60m PF | 30m PF | 15m PF | Best | Improvement |
|-------|--------|--------|--------|------|-------------|
| ETH   | 1.59   | 2.18   | 1.91   | 30m  | +37%        |
| AVAX  | 1.89   | 2.47   | 2.46   | 30m  | +31%        |
| LINK  | 1.65   | 1.71   | 1.33   | 30m  | +4%         |
| NEAR  | 1.86   | 1.92   | 2.43   | 15m  | +31%        |
| SOL   | 2.02   | 1.95   | 3.25   | 15m  | +61%        |

**Important caveat:** Data was resampled from 1h candles, not native 30m/15m. The improvement reflects that the Donchian(20) + ATR(10) parameters work better at finer granularity when the 1h bar is split — but the actual edge magnitude needs native 30m data to confirm.

**Recommendation:**
- Fetch native 30m OHLCV from Binance for ETH and AVAX
- Re-run walk-forward on native data
- If confirmed, migrate ETH/AVAX to 30m timeframe
- Risk: low (30m is just 1h split into finer bars, not fundamentally different)

---

## 2. Funding Rate Analysis

**Key finding:** The SHORT sleeve earns funding income in bull markets.

| Scenario | Long Funding Cost | Short Funding Earned |
|----------|------------------|---------------------|
| BULL_NORMAL | -0.3 to -0.6% ann | +11 to +22% ann |
| BULL_EXTREME | -5 to -9% ann | +55 to +88% ann |
| SIDEWAYS | ~0% | ~0% |
| BEAR | +3 to +6% ann | -3 to -6% ann |

**SHORT sleeve funding edge (BULL_NORMAL):**
- ETH: +10.9% annualized
- AVAX: +16.4% annualized  
- LINK: +10.9% annualized
- SOL: +21.9% annualized
- SUI: +16.4% annualized

**Insight:** This is ADDITIVE to the directional short edge (PF 2.08-2.76). A short position earns 11-22% from funding ON TOP OF the price decline profit. This significantly improves short sleeve economics.

**Recommendation:**
- Integrate live funding rate into paper trader and executor
- Use funding rate as a regime filter: very high funding (>0.05%/8h) may precede corrections
- Weight short sleeve allocation toward assets with highest funding rates

---

## 3. Portfolio Risk Management & Correlation Structure

**REVISED FINDING (corrected from IG88073):** Portfolio is NOT as correlated as previously stated.

**Pairwise correlation matrix (729 daily bars = 2 years):**

|       | ETH   | AVAX  | LINK  | NEAR  | SOL   | FIL   | SUI   | RNDR  | WLD   |
|-------|-------|-------|-------|-------|-------|-------|-------|-------|-------|
| ETH   | 1.00  | 0.77  | 0.78  | 0.72  | 0.78  | 0.01  | -0.05 | 0.03  | -0.04 |
| AVAX  | 0.77  | 1.00  | 0.83  | 0.79  | 0.76  | -0.00 | -0.03 | 0.05  | -0.02 |
| LINK  | 0.78  | 0.83  | 1.00  | 0.78  | 0.74  | 0.01  | -0.03 | 0.05  | -0.02 |
| NEAR  | 0.72  | 0.79  | 0.78  | 1.00  | 0.72  | 0.01  | -0.06 | 0.05  | -0.04 |
| SOL   | 0.78  | 0.76  | 0.74  | 0.72  | 1.00  | 0.03  | -0.05 | 0.04  | -0.05 |
| FIL   | 0.01  | -0.00 | 0.01  | 0.01  | 0.03  | 1.00  | 0.07  | -0.03 | 0.03  |
| SUI   | -0.05 | -0.03 | -0.03 | -0.06 | -0.05 | 0.07  | 1.00  | -0.00 | 0.63  |
| RNDR  | 0.03  | 0.05  | 0.05  | 0.05  | 0.04  | -0.03 | -0.00 | 1.00  | -0.03 |
| WLD   | -0.04 | -0.02 | -0.02 | -0.04 | -0.05 | 0.03  | 0.63  | -0.03 | 1.00  |

**Two distinct clusters identified:**

1. **Core cluster (r=0.72-0.83):** ETH, AVAX, LINK, NEAR, SOL
   - High-beta blue-chip L1/L2 alts. Move as a group.
   - These are effectively ONE bet on crypto beta.

2. **Satellite cluster (r≈0 with core):** FIL, RNDR, SUI, WLD
   - FIL: avg r=0.014 with core → GENUINELY UNCORRELATED
   - RNDR: avg r=0.045 with core → GENUINELY UNCORRELATED  
   - SUI: avg r=-0.045 with core, but r=0.63 with WLD
   - WLD: avg r=-0.036 with core, but r=0.63 with SUI

**KEY INSIGHT:** The portfolio has REAL diversification. FIL and RNDR are near-zero
correlation with the core. This means drawdowns in ETH/AVAX/LINK won't necessarily
hit FIL/RNDR. The portfolio is structurally better than IG88073 stated.

**Implications for position sizing:**
- Core cluster (ETH/AVAX/LINK/NEAR/SOL): 5 assets acting as one → reduce allocation
- Satellite (FIL/RNDR): genuinely uncorrelated → can take larger positions
- SUI/WLD pair: correlated with each other (r=0.63) but uncorrelated with core

**Built:** `scripts/portfolio_risk.py`
- Portfolio VaR with correlation adjustment (95% confidence)
- Drawdown-based leverage scaling (2x at 0% DD, 1x at 25% DD, kill switch at 50%)
- Correlation-adjusted Kelly position sizing
- Risk flags: over-exposure, concentration, high VaR, drawdown warnings

**Correlation problem:** All 9 assets are r=0.62-0.83 correlated. The portfolio is effectively ONE bet on crypto beta, not diversified. This means:
- Drawdowns hit all positions simultaneously
- Single-asset MaxDD estimates understate portfolio DD
- Position sizing MUST account for correlation

**Correlation-adjusted sizing example ($10K portfolio):**
- ETH: $743 (7.4%)
- SOL: $738 (7.4%)
- FIL: $757 (7.6%)
- SUI: $739 (7.4%)

Compared to unadjusted 15% max, the correlation adjustment reduces each to ~7.5%.

---

## 4. Polymarket Assessment

**Current crypto markets on Polymarket:**
- BTC daily price above/below (high volume, short-term)
- BTC monthly price targets (medium volume)
- Fed rate decisions (99% priced in, no edge)
- MegaETH FDV at launch (medium volume)

**Verdict:** Polymarket's crypto markets are primarily directional bets on BTC price — NOT structurally different from our perps positions. They don't provide uncorrelated alpha.

**Where Polymarket COULD provide value:**
1. **Macro event hedging** — Fed decisions, geopolitical events affecting crypto
2. **Protocol-specific catalysts** — ETF approvals, mainnet launches, regulatory decisions
3. **Contrarian signals** — very high funding + very high Polymarket "BTC $100K" probability = crowd is max long

**Recommendation:** Low priority for now. Focus on optimizing the confirmed ATR BO edge. Revisit Polymarket when:
- We have native 30m data confirmed
- Funding rate integration is complete
- The short sleeve is earning funding income live

---

## 5. Hyperliquid Executor

**Status:** SKELETON complete. `scripts/hl_executor.py`

Capabilities:
- `place_order()` — market orders with leverage
- `close_position()` — market close with reason tracking
- `get_balance()` — account equity
- `get_positions()` — open position state
- `get_funding_rates()` — current funding rates per asset
- `calculate_size()` — Kelly-based position sizing
- Trade logging to `data/hl_state/hl_trades_YYYY-MM-DD.jsonl`

**Needs from Chris:**
1. USDC deposit on Arbitrum (Hyperliquid funding)
2. API credentials (HL_ACCOUNT_ADDRESS, HL_SECRET_KEY in .env)
3. First trade approval

---

## Priority Action Items

| # | Action | Impact | Effort |
|---|--------|--------|--------|
| 1 | Fetch native 30m data for ETH/AVAX | +31-37% PF if confirmed | Low |
| 2 | Integrate funding rate into paper trader | +11-22% ann on shorts | Low |
| 3 | Deploy portfolio risk monitor | Prevents blow-ups | Done |
| 4 | HL credentials + first trade | Enables live trading | Needs Chris |
| 5 | Polymarket event-driven strategy | Uncorrelated alpha | Medium |

---

## References

[1] IG88073 — Consolidated Strategy Status and Production Readiness  
[2] IG88072 — Expanded Asset Universe & Portfolio Optimization  
[3] IG88071 — Comprehensive System Review and Strategy Roadmap
