# Bollinger-Band-Percent-B Primitive

## Profile
- **Signal Type**: Mean Reversion
- **Applicable Timeframes**: 1h, 4h
- **Applicable Assets**: All Liquid Assets
- **Orthogonality**: Measures price relative to volatility bands; identifies extreme overbought/oversold conditions relative to a moving average.

## Logic
B% = (Price - LowerBand) / (UpperBand - LowerBand). Signal: B% <<  0.2 (Oversold) or B% > 0.8 (Overbought).

## Failure Modes
- Strong trending markets (Price 'walks the bands' while remaining overbought/oversold).

## Proven Compositions
- Contrast with H3-Trend to avoid buying the top of a parabolic move.
