# Volatility-Squeeze-Keltner Primitive

## Profile
- **Signal Type**: Volatility/Regime
- **Applicable Timeframes**: 4h, 1d
- **Applicable Assets**: All Liquid Assets
- **Orthogonality**: Detects periods of extreme compression (low vol) that typically precede explosive breakouts.

## Logic
BB-Band width << K Keltner-Channel width. Signal: Squeeze = True.

## Failure Modes
- False breakouts (head-fakes) where the squeeze releases but immediately reverses.

## Proven Compositions
- Use as a 'Coiled Spring' filter; H3-Trend signals firing immediately after a squeeze are high-conviction.
