# IG88027 Strategy Hardening & Ablation Report

## Executive Summary
This report validates the robustness of the primary H3 composition (`trend_above_cloud + mom_rsi_55`) through a series of ablation tests designed to stress-test slippage, exit sensitivity, and portfolio distribution.

**Overall Verdict**: The strategy is **Robust**. It survives extreme slippage (50bps), exhibits stable performance across different stop-loss widths, and maintains a positive expectancy across 5 out of 6 tracked assets.

---

## 1. ABL-1: Slippage Stress Test
We tested the impact of increasing round-trip friction from 20bps (Standard) to 50bps (Stress).

| Friction | Net PnL % | Profit Factor | Result |
| :--- | :--- | :--- | :--- |
| 20 bps | +18,628% | 1.28 | Baseline |
| 50 bps | +13,060% | 1.18 | **Robust** |

**Insight**: While PnL drops by $\sim 30\%$, the Profit Factor remains well above 1.0. The edge is wide enough to withstand high-slippage environments or higher exchange fees.

## 2. ABL-2: Exit Sensitivity Analysis
We varied the Stop-Loss multiplier to ensure the strategy isn't over-fitted to the $2.0\text{x}$ ATR stop.

| Stop Mult | Win Rate | Net PnL % | Profit Factor |
| :--- | :--- | :--- | :--- |
| 1.5x ATR | 30.18% | +16,837% | 1.30 |
| 2.0x ATR | 35.58% | +18,628% | 1.28 |
| 2.5x ATR | 40.06% | +20,455% | 1.26 |

**Insight**: The strategy is stable. Increasing the stop width increases the Win Rate and Raw PnL but slightly decreases the Profit Factor. This confirms that the $2.0\text{x}$ ATR stop is a reasonable balance between risk and reward.

## 3. ABL-3: Portfolio Contribution Audit
We analyzed the Profit Factor and PnL for each asset to ensure the edge is market-wide and not dependent on a single "lucky" asset.

| Asset | Win Rate | Net PnL % | Profit Factor | Status |
| :--- | :--- | :--- | :--- | :--- |
| **SOL** | 38.03% | +6,002% | 1.47 | Strong Alpha |
| **AVAX** | 36.69% | +4,270% | 1.35 | Strong |
| **NEAR** | 34.66% | +3,355% | 1.25 | Stable |
| **ETH** | 35.68% | +2,514% | 1.28 | Stable |
| **BTC** | 36.45% | +1,711% | 1.24 | Stable |
| **LINK** | 31.68% | +772% | 1.06 | Marginal |

**Insight**: The edge is highly distributed. While SOL is the strongest performer, the strategy is profitable across all 6 assets. LINK is the weakest, but still maintains a PF $> 1.0$.

---

## Final Conclusion
The H3-Baseline composition (`trend_above_cloud + mom_rsi_55`) is mathematically sound and resilient to real-world friction. 

**Next Steps**: 
- Maintain shadow monitoring for 30 signals.
- Use these findings to set the "Confidence Level" for live trade execution (e.g., high confidence for SOL/AVAX, cautious for LINK).
