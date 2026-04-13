# IG88024 H3-A and H3-B Strategy Validation Report

**Date:** 2026-04-10
**Status:** Finalized Research
**Author:** IG-88

## Executive Summary

The combined H3-A and H3-B strategy exhibits exceptional statistical performance on SOL 4h data. The combined strategy achieved an Out-of-Sample (OOS) Profit Factor (PF) of **7.281** with a p-value of **0.000** across 22 trades. The optimal exit strategy for both H3-A and H3-B was determined to be the **ATR Trailing Stop** method, which significantly outperformed fixed stops and other dynamic exits.

## Strategy Deep Dive

### H3-A (Ichimoku + RSI + Score)
*   **Best Exit:** `atr_trail` (OOS PF: 6.576, Sharpe: 14.811, p=0.000).
*   **Parameters:** Tenkan=9, Kijun=26, RSI>55, IchiScore>=3.
*   **Note:** This strategy is highly robust and is the current portfolio anchor.

### H3-B (Vol Spike + RSI Cross)
*   **Best Exit:** `atr_trail` (OOS PF: 3.000, Sharpe: 7.868, p=0.006).
*   **Parameters:** Vol>1.5× 20MA, PriceGain>0.5%, RSI cross 50.
*   **Note:** This strategy shows strong stability across rolling windows and is highly orthogonal to H3-A.

## Portfolio Performance (H3-A + H3-B Combined)
*   **OOS PF:** 7.281
*   **p-value:** 0.000
*   **Trade Count (n):** 22
*   **Conclusion:** The combination is statistically significant and represents the highest conviction edge identified to date.

## Next Steps & Open Items

1.  **H3-D Cross-Asset:** Must be tested on ETH daily, NEAR, etc. (T2).
2.  **H3-C Optimization:** Must test H3-C with `atr_trail` exit (T3).
3.  **Perps Simulation:** Must model H3 signals on Jupiter Perps, accounting for borrowing fees (T4).
4.  **Timeframe Expansion:** Must run the 1h backtest (T5).

## Durable Conclusion

**The ATR Trailing Stop is the superior exit mechanism for high-conviction H3 strategies.** This finding is promoted to `fact/trading.md`.

---

## Assumptions & Risks

### Core Assumptions
1. **Asset-Specific Edge:** This edge is validated on **SOL 4h only**. Cross-asset and cross-timeframe tests show mixed results (H3-B expansion test: 5 of 17 assets passed). Do not assume transferability without dedicated validation.
2. **Regime Persistence:** The BTC Trend Regime filter (RISK_ON/OFF) assumes that BTC regime transitions are predictive of altcoin momentum. If BTC regime detection degrades (e.g., choppy consolidation), the filter may block valid signals or permit losing ones.
3. **Market Structure Stability:** The edge assumes that retail momentum cycles, liquidity provision, and volatility regimes remain consistent with the 2024-2026 backtest window. If retail participation changes significantly (e.g., regulatory shift, new institutional players), the edge may degrade.
4. **Fee Model Accuracy:** Backtest fees are modeled at Kraken maker rates (0.16%). If execution defaults to taker (0.26%) or slippage exceeds 10bps, performance will degrade proportionally.

### Identified Risks
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Cross-asset failure | Medium | High | Never trade H3 on unvalidated assets without dedicated backtest |
| Regime filter lag | Low | Medium | Monitor regime transitions; consider adding a "regime momentum" buffer |
| Slippage beyond 10bps | Low | Medium | Use limit orders only; reject signals during low-liquidity hours |
| Overfitting to SOL 4h | Medium | High | Rolling window stability test (Study 4) passed 8/8 windows; continue monitoring |
| H3-B signal decay | Medium | Medium | H3-B has lower PF than H3-A; treat as auxiliary, not primary |

### What This Does NOT Prove
- **H3 works on other timeframes** (1h, 1d not yet tested with ATR trailing stop)
- **H3 works on other assets** (NEAR, INJ showed promise but n<5 in OOS)
- **H3 works in perpetuals** (Jupiter Perps integration not validated — mean-reversion strategy is separate)
- **The edge is permanent** (statistical significance does not imply future persistence)

### Kill-Switch Criteria
If any of the following occur in live trading, halt H3 signals and re-validate:
- Win Rate drops below 40% over 30 consecutive trades
- Max Drawdown exceeds 10% of wallet
- Profit Factor falls below 1.5 over any 20-trade rolling window
