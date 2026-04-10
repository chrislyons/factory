# IG88024 H3-A and H3-B Strategy Validation Report

**Date:** 2026-04-10
**Status:** Finalized Research
**Author:** IG-88

## Executive Summary

The combined H3-A and H3-B strategy exhibits exceptional statistical performance on SOL 4h data. The combined strategy achieved an Out-of-Sample (OOS) Profit Factor (PF) of **7.281** with a p-value of **0.000** across 22 trades. The optimal exit strategy for both H3-A and H3-B was determined to be the **ATR Trailing Stop** method, which significantly outperformed fixed stops and other dynamic exits.

## Strategy Deep Dive

### H3-A (Ichimoku + RSI + Score)
*   **Best Exit:**  (OOS PF: 6.576, Sharpe: 14.811, p=0.000).
*   **Parameters:** Tenkan=9, Kijun=26, RSI>55, IchiScore>=3.
*   **Note:** This strategy is highly robust and is the current portfolio anchor.

### H3-B (Vol Spike + RSI Cross)
*   **Best Exit:**  (OOS PF: 3.000, Sharpe: 7.868, p=0.006).
*   **Parameters:** Vol>1.5× 20MA, PriceGain>0.5%, RSI cross 50.
*   **Note:** This strategy shows strong stability across rolling windows and is highly orthogonal to H3-A.

## Portfolio Performance (H3-A + H3-B Combined)
*   **OOS PF:** 7.281
*   **p-value:** 0.000
*   **Trade Count (n):** 22
*   **Conclusion:** The combination is statistically significant and represents the highest conviction edge identified to date.

## Next Steps & Open Items

1.  **H3-D Cross-Asset:** Must be tested on ETH daily, NEAR, etc. (T2).
2.  **H3-C Optimization:** Must test H3-C with  exit (T3).
3.  **Perps Simulation:** Must model H3 signals on Jupiter Perps, accounting for borrowing fees (T4).
4.  **Timeframe Expansion:** Must run the 1h backtest (T5).

## Durable Conclusion

**The ATR Trailing Stop is the superior exit mechanism for high-conviction H3 strategies.** This finding is promoted to .
