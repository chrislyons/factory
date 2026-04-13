# Volume-Ignition Primitive

## Profile
- **Signal Type**: Volatility/Confirmation (e.g., Trend, Momentum, Volatility, Regime)
- **Applicable Timeframes**: 1h, 4h
- **Applicable Assets**: All Liquid Assets
- **Orthogonality**: Validates price movement with capital flow. (How this differs from other indicators)

## Logic
Current Volume > 1.5x SMA(20) of Volume.

## Failure Modes
- Fake-outs during low-liquidity gaps, news-driven spikes without trend.

## Proven Compositions
- H3-B
