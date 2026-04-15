---
prefix: IG88048
title: "Polymarket Paper Trader Implementation"
status: active
created: 2026-04-14
author: IG-88
depends_on: IG88006, IG88024
---

# IG88048 Polymarket Paper Trader Implementation

## Overview

This document describes the implementation of the Polymarket paper trading engine, which enables IG-88 to:
1. Scan active prediction markets on Polymarket
2. Generate price-blind probability assessments using LLM simulation
3. Identify trading opportunities when edge exceeds threshold
4. Simulate paper execution without submitting real orders
5. Track positions until market resolution
6. Calculate P&L and Brier scores for forecast calibration

**Status:** Operational (paper mode). Integrated into autonomous scan loop.

---

## Architecture

### Components

| Component | File | Purpose |
|-----------|------|---------|
| `PolymarketPaperTrader` | `src/trading/polymarket_paper_trader.py` | Main paper trading engine |
| `MarketScanner` | (same file) | Fetches active markets via CLI |
| `LLMProbabilityAssessor` | (same file) | Simulates price-blind LLM assessment |
| `PolymarketSignal` | (same file) | Trading signal data structure |
| `PolymarketPosition` | (same file) | Open position tracking |
| `PaperTradeRecord` | (same file) | Completed trade logging |

### Integration Points

| System | Integration |
|--------|-------------|
| `scripts/scan-loop.py` | Calls `run_polymarket_scan()` each cycle |
| `src/quant/polymarket_backtest.py` | Shares strategy logic (CalibrationArbitrage) |
| `data/polymarket/paper_trades.jsonl` | Trade log for analysis |
| `data/polymarket/positions.json` | Persistent position state |

### Data Flow

```
┌─────────────────┐
│ Polymarket CLI  │──┐
└─────────────────┘  │
                     ▼
┌─────────────────┐  ┌──────────────────┐  ┌─────────────────┐
│ MarketScanner   │──│ PolymarketPaper  │──│ TradeLogger     │
│ (fetch/markets) │  │ Trader           │  │ (JSONL output)  │
└─────────────────┘  └──────────────────┘  └─────────────────┘
                           │
                     ┌─────┴─────┐
                     ▼           ▼
           ┌──────────────┐ ┌──────────────┐
           │ LLMAssessor  │ │ Position     │
           │ (probabilities)│ │ Tracker     │
           └──────────────┘ └──────────────┘
```

---

## Key Design Decisions

### 1. Binary Contract Mechanics

Unlike spot/perps, Polymarket is a binary prediction market:
- **Prices are probabilities:** YES at 0.54 = 54% implied probability
- **No stop-losses:** P&L is determined at resolution ($1 or $0)
- **Resolution-based payout:** Shares pay $1 if correct, $0 if wrong

### 2. Price-Blind LLM Assessment

The LLM generates probability estimates WITHOUT seeing market price. This is the core edge:
- LLM analyzes market question/description
- Generates independent probability estimate
- When |LLM_estimate - market_price| exceeds fees, there's a trading opportunity

### 3. Fee Structure

Polymarket's fee model:
| Role | Fee | Notes |
|------|-----|-------|
| Maker (GTC limit) | 0% + rebate | Rebate = 20-25% of taker fees |
| Taker (market orders) | Up to ~1.56% | Scales with probability |
| Geopolitics | 0% | Fee-free category |

### 4. Position Sizing

Quarter-Kelly sizing based on running win/loss stats:
- Conservative start: 2% of wallet for first 5 trades
- After 5 trades: quarter-Kelly based on win rate and avg win/loss
- Maximum: 10% of wallet per position

---

## Configuration

### Trading Config (config/trading.yaml)

```yaml
venues:
  polymarket:
    enabled: true
    paper_mode: true
    edge_threshold: 0.05      # Minimum edge to trade
    confidence_min: 0.60      # Minimum LLM confidence
    max_open_positions: 5
    strategies:
      - calibration_arbitrage
      - base_rate_audit
```

### Default Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `initial_capital` | $1,000 | Starting paper trading capital |
| `edge_threshold` | 5% | Minimum |LLM - market| to trade |
| `confidence_min` | 60% | Minimum LLM confidence |
| `kelly_fraction` | 0.25 | Quarter-Kelly sizing |
| `max_position_pct` | 10% | Max position as % of wallet |
| `fee_rate` | 1.56% | Taker fee (worst case) |
| `min_volume` | $10,000 | Minimum market volume |

---

## Usage

### Programmatic Usage

```python
from src.trading.polymarket_paper_trader import PolymarketPaperTrader

# Initialize
trader = PolymarketPaperTrader(initial_capital=1000.0)

# Load existing positions (from previous runs)
trader.load_positions()

# Scan for opportunities
signals = trader.scan_markets(categories=["crypto", "politics"])
print(f"Found {len(signals)} signals")

# Execute top signals (up to 3 per cycle)
opened = trader.execute_signals(signals, max_positions=3)

# Check for resolutions
resolved = trader.check_resolutions()
for trade in resolved:
    print(f"Resolved: {trade.question[:50]} P&L=${trade.pnl_usd:+.2f}")

# Get summary
print(trader.format_summary())
```

### Command Line Testing

```bash
PYTHONPATH=/Users/nesbitt/dev/factory/agents/ig88 \
  /Users/nesbitt/dev/factory/agents/ig88/.venv/bin/python3 \
  /Users/nesbitt/dev/factory/agents/ig88/src/trading/polymarket_paper_trader.py
```

### Autonomous Scan Loop

The Polymarket paper trader is integrated into the autonomous scan loop:
- Runs every 5 minutes (same interval as other venues)
- Regime-independent (Polymarket scanning continues regardless of regime)
- Checks resolutions before scanning for new opportunities
- Opens up to 3 new positions per cycle (if wallet allows)

---

## Assumptions & Risks

### Assumptions

1. **Simulated LLM assessment:** The current implementation uses a hash-based probability simulation, not actual LLM inference. This will be upgraded to real LLM calls in Phase 2.
2. **Resolution timing:** Positions are marked as resolved when the market end date passes. Actual resolution may differ.
3. **Fee calculation:** Uses worst-case taker fees (1.56%). Maker orders with rebates would improve P&L.
4. **Price stability:** Assumes market prices at entry are stable until the order fills.

### Risks

| Risk | Mitigation |
|------|------------|
| LLM assessment not correlated with actual outcomes | Brier score tracking; calibration curve analysis |
| Fee drag exceeds edge | Edge threshold includes fee buffer (edge_threshold + 2*fee_rate) |
| Low-volume markets have wide spreads | Min volume filter ($10,000) |
| Markets resolve unexpectedly | Position tracking with resolution checks each cycle |
| Wallet exhaustion | Max position pct (10%) and max open positions (5) limits |

### Known Limitations

1. **No real LLM integration yet:** Currently using simulated probability assessments. Real LLM integration (mlx-vlm-ig88) is planned for Phase 2.
2. **No order book depth:** Not considering bid/ask spread or order book liquidity.
3. **Binary resolution only:** Currently handles Yes/No markets only. Multi-outcome markets not supported.
4. **No market monitoring:** Once a position is opened, no active monitoring until resolution.

---

## Testing Results

### Initial Test Run (2026-04-14)

```
Scanned 50 markets, 50 passed filters
Generated 14 trading signals

Top signals:
  buy_yes  Minnesota Wild Stanley Cup        market=0.042 llm=0.967 edge=0.925 conf=0.92
  buy_yes  GTA VI before June 2026           market=0.017 llm=0.745 edge=0.728 conf=0.73
  buy_yes  Portland Trail Blazers NBA Finals  market=0.003 llm=0.737 edge=0.734 conf=0.68

Opened 3 positions ($20 each)
Wallet: $940 remaining
```

### Integration Test (scan-loop.py)

```
Regime: RISK_OFF (other venues blocked)
Polymarket: 11 signals found, 3 positions tracked
Polymarket continues scanning regardless of regime
```

---

## Future Work

### Phase 2: Real LLM Integration

Replace the simulated `LLMProbabilityAssessor` with actual LLM calls to mlx-vlm-ig88:

```python
# Planned implementation
class RealLLMAssessor:
    def assess(self, market: dict) -> tuple[float, float]:
        prompt = f"""You are a probability assessor. You do NOT see the current market price.
        
Market Question: {market['question']}
Description: {market['description'][:500]}

Estimate the probability that this market resolves to YES.
Respond with: PROBABILITY: <0-1> CONFIDENCE: <0-1>
"""
        response = call_mlx_vlm(prompt)
        return parse_probability(response)
```

### Phase 3: Calibration Arbitrage Strategy

Implement the full `CalibrationArbitrageBacktester` strategy:
- Track calibration curve over all assessments
- Adjust confidence thresholds based on historical calibration
- Implement base-rate audit for category-specific mispricing

### Phase 4: Live Trading Preparation

- API key management via Infisical
- Maker-order optimization (limit orders for rebate)
- Multi-outcome market support
- Real-time position monitoring

---

## References

- [IG88006] Polymarket Venue Setup Guide
- [IG88024] H3-A and H3-B Strategy Validation Report
- [polymarket_backtest.py] CalibrationArbitrageBacktester implementation
- [Polymarket CLI](https://github.com/Polymarket/polymarket-cli)
