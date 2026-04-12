# IG88026 Combinatorial Strategy Analysis - Indicator Primitives

## Executive Summary
This report details the results of a systematic combinatorial search for the optimal indicator composition across 6 validated assets (SOL, BTC, ETH, LINK, AVAX, NEAR) on the 4h timeframe. 

The goal was to move away from hand-coded strategies and identify which "Indicator Primitives" provide the highest net PnL when combined.

## 1. Methodology
We defined four core primitives:
- **`trend_above_cloud`**: Price > Ichimoku Senkou Span A & B.
- **`mom_rsi_55`**: RSI(14) > 55.
- **`mom_rsi_cross`**: RSI(14) crosses above 50.
- **`vol_ignition`**: Volume > 1.5x SMA(20) of Volume.

The `CompositionTester` iterated through all combinations of 2 or 3 primitives, treating them as an "AND" gate for entry. 
- **Entry**: All primitives in the composition must be true.
- **Exit**: 2x ATR Stop or 5x ATR Target.
- **Sample Size**: 18k+ trades for the top composition.

## 2. Top Performing Compositions

| Composition | Trades | Win Rate | Net PnL % | Rank |
| :--- | :--- | :--- | :--- | :--- |
| `trend_above_cloud` + `mom_rsi_55` | 18,559 | 35.58% | +22,340% | 1 |
| `mom_rsi_55` + `vol_ignition` | 4,510 | 37.25% | +7,020% | 2 |
| `trend_above_cloud` + `vol_ignition` | 4,642 | 36.60% | +6,460% | 3 |
| `trend_above_cloud` + `mom_rsi_55` + `vol_ignition` | 3,800 | 37.29% | +5,797% | 4 |

## 3. Key Insights
- **Trend Dominance**: Every top-3 composition includes either a trend primitive or a volatility primitive. The combination of `trend_above_cloud` and `mom_rsi_55` is overwhelmingly the most profitable, primarily due to its high trade frequency and capture of major trend moves.
- **Volume as a Filter**: Adding `vol_ignition` significantly reduces trade count (from 18k to 4k) but maintains a similar win rate. This suggests volume acts as a high-conviction filter rather than a primary alpha driver.
- **The "Sweet Spot"**: The 2-primitive compositions outperform 3-primitive compositions in net PnL, suggesting that over-filtering (adding a 3rd primitive) leads to "missing the meat" of the trend.

## 4. Implementation Plan
The composition `trend_above_cloud + mom_rsi_55` will be established as the baseline "High-Frequency Trend" strategy. 
The composition `mom_rsi_55 + vol_ignition` will be utilized for "High-Conviction" entries.

These findings will be used to refine the `h3_scanner.py` logic as we move toward the 30-signal graduation target.
