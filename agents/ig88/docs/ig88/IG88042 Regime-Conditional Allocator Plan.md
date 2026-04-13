# IG88042: Regime-Conditional Allocator Plan

**Date:** 2026-04-13
**Author:** IG-88
**Status:** Plan for Implementation

---

## Executive Summary

A regime-conditional allocator that dynamically weights between Mean Reversion (MR) and Trend Following (H3) strategies based on BTC market regime detection. The allocator uses BTC 20-bar return as the primary regime signal, with pair-specific position sizing based on validated expectancy.

---

## Regime Definition

### Primary Signal: BTC 20-Bar Return

| Regime | BTC 20-Bar Return | Description | MR Weight | H3 Weight |
|--------|-------------------|-------------|-----------|-----------|
| RISK_OFF | < -8% | Severe downtrend | 0% | 0% |
| BEARISH | -8% to -3% | Mild downtrend | 40% | 20% |
| RANGING | -3% to +3% | Neutral/sideways | 80% | 20% |
| BULLISH | +3% to +8% | Mild uptrend | 50% | 50% |
| EUPHORIA | > +8% | Strong uptrend | 30% | 70% |

### Secondary Signal: BTC 200-SMA Position

| Condition | Implication |
|-----------|-------------|
| Price > 200-SMA | Macro uptrend — favor trend strategies |
| Price < 200-SMA | Macro downtrend — favor mean reversion, reduce size |

### Tertiary Signal: 30-Day Realized Volatility

| Volatility | Implication |
|------------|-------------|
| < 2% daily | Low vol — MR dominates |
| 2-4% daily | Normal — balanced |
| > 4% daily | High vol — H3 dominates, reduce overall size |

---

## Strategy Definitions

### Mean Reversion (MR) — Works in RANGING regime

**Pair-Specific Parameters (from validation):**

| Pair | RSI | BB σ | Vol | Entry | Stop | Target | PF | Exp% |
|------|-----|------|-----|-------|------|--------|-----|------|
| SOL | <30 | 1.5 | >1.8 | T1 | 0.5% | 10% | 2.44 | 0.89 |
| NEAR | <30 | 1.5 | >1.8 | T2 | 0.5% | 12.5% | 3.25 | 1.35 |
| LINK | <30 | 2.0 | >1.8 | T1 | 0.5% | 15% | 3.47 | 1.45 |
| AVAX | <30 | 1.5 | >1.8 | T2 | 0.5% | 12.5% | 3.88 | 1.61 |
| ATOM | <30 | 1.5 | >1.5 | T1 | 0.5% | 12.5% | 3.43 | 1.39 |
| UNI | <40 | 1.5 | >2.0 | T2 | 0.5% | 15% | 2.89 | 1.15 |
| AAVE | <35 | 1.5 | >1.5 | T1 | 0.5% | 15% | 2.88 | 1.10 |
| ARB | <30 | 1.5 | >1.8 | T2 | 0.5% | 15% | 2.97 | 1.21 |
| OP | <25 | 1.0 | >1.3 | T1 | 0.5% | 15% | 3.90 | 1.72 |
| INJ | <30 | 1.0 | >1.5 | T2 | 0.5% | 7.5% | 3.29 | 1.26 |
| SUI | <30 | 1.0 | >1.8 | T2 | 0.5% | 15% | 5.43 | 2.34 |
| POL | <35 | 1.0 | >1.3 | T2 | 0.5% | 10% | 2.16 | 0.71 |

### Trend Following (H3) — Works in BULLISH/EUPHORIA regime

**H3-A: Ichimoku Convergence (SOL only)**
- Conditions: TK cross + Above cloud + RSI > 40 + BTC 20-bar > 0%
- Exit: T10 (10 bars)
- PF: 2.27, Exp: 2.07%

**H3-B: Volume Ignition (SOL, AVAX)**
- Conditions: Vol > 1.5x + Price gain > 0.5% + RSI cross 50 + BTC 20-bar > 0%
- Exit: T10
- SOL: PF 4.12, Exp: 2.95%
- AVAX: PF 1.83, Exp: 1.48%

---

## Position Sizing

### Kelly Criterion (Half-Kelly)

Position size = (Expectancy / Breakeven) × Account_Risk × 0.5

**Pair-Specific Half-Kelly:**

| Pair | Exp% | Half-Kelly | Max Position |
|------|------|------------|--------------|
| SOL | 0.89% | 12.5% | 12.5% |
| NEAR | 1.35% | 6.9% | 6.9% |
| LINK | 1.45% | 7.7% | 7.7% |
| AVAX | 1.61% | 11.4% | 11.4% |
| SUI | 2.34% | 8.0% | 8.0% |
| OP | 1.72% | 9.5% | 9.5% |

*Note: These are per-trade maximums. Total portfolio exposure capped at 50%.*

### Position Size Caps

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Max per trade | 10% of portfolio | Diversification |
| Max per pair | 20% of portfolio | Concentration limit |
| Max total exposure | 50% of portfolio | Cash buffer |
| Max correlated positions | 4 | Reduce correlation risk |

---

## Allocator Logic Flow

```
1. READ: BTC 20-bar return, BTC price vs 200-SMA, 30-day realized vol

2. DETERMINE REGIME:
   IF BTC 20-bar < -8%: → RISK_OFF (no new positions)
   ELIF BTC 20-bar < -3%: → BEARISH (40% MR / 20% H3)
   ELIF BTC 20-bar < +3%: → RANGING (80% MR / 20% H3)
   ELIF BTC 20-bar < +8%: → BULLISH (50% MR / 50% H3)
   ELSE: → EUPHORIA (30% MR / 70% H3)

3. APPLY MACRO ADJUSTMENT:
   IF BTC < 200-SMA: Reduce all weights by 25%

4. APPLY VOLATILITY ADJUSTMENT:
   IF 30d vol > 4%: Reduce all weights by 25%

5. SCAN FOR SIGNALS:
   For each pair in active strategies:
   - Check entry conditions
   - Verify position size within limits
   - Execute if conditions met

6. MANAGE EXISTING POSITIONS:
   - Check stops and targets
   - Trail if profitable
   - Exit if regime shifts to RISK_OFF
```

---

## Implementation Requirements

### Data Requirements

| Data Point | Source | Update Frequency |
|------------|--------|------------------|
| BTC 4h OHLCV | Binance | Every 4 hours |
| BTC 200-SMA | Calculated | Every 4 hours |
| 30-day realized vol | Calculated | Daily |
| Pair-specific OHLCV | Binance | Every 4 hours |

### State Management

Track in `data/allocator_state.json`:
```json
{
  "current_regime": "RANGING",
  "btc_20bar_return": 0.012,
  "btc_above_200sma": true,
  "realized_vol_30d": 0.028,
  "active_positions": [...],
  "last_scan_time": "2026-04-13T12:00:00Z"
}
```

### Position Tracking

Track in `data/active_positions.json`:
```json
{
  "positions": [
    {
      "pair": "SOL",
      "strategy": "MR",
      "entry_price": 145.32,
      "entry_time": "2026-04-13T08:00:00Z",
      "stop_price": 144.59,
      "target_price": 162.76,
      "size_pct": 8.0,
      "status": "OPEN"
    }
  ]
}
```

---

## Risk Limits

### Hard Limits (Kill Switch)

| Condition | Action |
|-----------|--------|
| BTC 20-bar < -10% | Close all, go to cash |
| Portfolio drawdown > 8% | Halt new positions |
| Any pair drawdown > 5% | Reduce size 50% |
| Correlation spike > 0.8 | Reduce to 3 pairs max |

### Soft Limits (Warnings)

| Condition | Action |
|-----------|--------|
| BTC 20-bar < -5% | Flag for review |
| 3 consecutive losses on same pair | Review parameters |
| 30d realized vol > 5% | Reduce all sizes 25% |

---

## Monitoring

### Daily Checks
1. Regime status and any transitions
2. Open position P&L
3. Stop/target triggers
4. Friction/slippage vs expected

### Weekly Review
1. Pair-level performance vs backtest
2. Strategy-level PF
3. Parameter drift detection
4. Walk-forward stability check

---

## Next Steps

1. **Implement regime detection** — Script to compute BTC 20-bar return and determine regime
2. **Build signal scanner** — Scan all 12 pairs for MR/H3 signals per regime
3. **Position manager** — Track entries, exits, stops, targets
4. **Paper trading** — Run in simulation before live deployment
5. **Alert system** — Notify on regime transitions and trade executions

---

## Appendix: All Validated Parameters

### MR Parameters (12 Pairs)

```python
MR_PARAMS = {
    'SOL':  {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 1, 'stop': 0.005, 'target': 0.10},
    'NEAR': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.125},
    'LINK': {'rsi': 30, 'bb': 2.0, 'vol': 1.8, 'entry': 1, 'stop': 0.005, 'target': 0.15},
    'AVAX': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.125},
    'ATOM': {'rsi': 30, 'bb': 1.5, 'vol': 1.5, 'entry': 1, 'stop': 0.005, 'target': 0.125},
    'UNI':  {'rsi': 40, 'bb': 1.5, 'vol': 2.0, 'entry': 2, 'stop': 0.005, 'target': 0.15},
    'AAVE': {'rsi': 35, 'bb': 1.5, 'vol': 1.5, 'entry': 1, 'stop': 0.005, 'target': 0.15},
    'ARB':  {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.15},
    'OP':   {'rsi': 25, 'bb': 1.0, 'vol': 1.3, 'entry': 1, 'stop': 0.005, 'target': 0.15},
    'INJ':  {'rsi': 30, 'bb': 1.0, 'vol': 1.5, 'entry': 2, 'stop': 0.005, 'target': 0.075},
    'SUI':  {'rsi': 30, 'bb': 1.0, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.15},
    'POL':  {'rsi': 35, 'bb': 1.0, 'vol': 1.3, 'entry': 2, 'stop': 0.005, 'target': 0.10},
}
```

### H3 Parameters

```python
H3A_PARAMS = {
    'exit_bars': 10,
    'rsi_thresh': 40,
    'require_tk': True,
    'require_cloud': True,
    'min_score': 3,
    'btc_regime_min': 0.0,  # BTC 20-bar must be > 0%
}

H3B_PARAMS = {
    'exit_bars': 10,
    'vol_mult': 1.5,
    'rsi_thresh': 50,
    'gain_pct': 0.005,
    'btc_regime_min': 0.0,
}
```

---

*Generated: 2026-04-13 | IG-88 Allocator Design*
