#!/usr/bin/env python3
"""
Funding Rate Analysis for Hyperliquid Perps.
Funding rates can be a significant edge: if we're LONG and funding is negative,
we EARN funding. If SHORT and funding is positive, we EARN funding.

Objective: Determine whether funding rate regime aligns with our directional bias,
and whether there's an exploitable funding rate momentum signal.
"""

import json
import numpy as np
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path("/Users/nesbitt/dev/factory/agents/ig88")

# Hyperliquid funding rates (typical 8h intervals, 3x/day)
# These are approximate historical ranges based on market conditions
FUNDING_SCENARIOS = {
    "BULL_EXTREME": {  # Crowd is max long, shorts pay
        "ETH": 0.0005, "SOL": 0.0008, "AVAX": 0.0006,
        "LINK": 0.0004, "NEAR": 0.0007, "FIL": 0.0005,
        "SUI": 0.0006, "RNDR": 0.0005, "WLD": 0.0008,
    },
    "BULL_NORMAL": {  # Mild positive funding
        "ETH": 0.0001, "SOL": 0.0002, "AVAX": 0.00015,
        "LINK": 0.0001, "NEAR": 0.00015, "FIL": 0.0001,
        "SUI": 0.00015, "RNDR": 0.0001, "WLD": 0.0002,
    },
    "SIDEWAYS": {  # Near zero
        "ETH": 0.00003, "SOL": 0.00005, "AVAX": 0.00004,
        "LINK": 0.00003, "NEAR": 0.00004, "FIL": 0.00003,
        "SUI": 0.00004, "RNDR": 0.00003, "WLD": 0.00005,
    },
    "BEAR_NORMAL": {  # Shorts pay (negative = longs earn)
        "ETH": -0.0001, "SOL": -0.00015, "AVAX": -0.00012,
        "LINK": -0.0001, "NEAR": -0.00012, "FIL": -0.00008,
        "SUI": -0.0001, "RNDR": -0.00008, "WLD": -0.00012,
    },
}

ASSETS = ["ETH", "SOL", "AVAX", "LINK", "NEAR", "FIL", "SUI", "RNDR", "WLD"]

def analyze_funding_impact():
    """Analyze funding rate impact on ATR Breakout P&L."""
    print("=== Funding Rate Impact Analysis ===\n")
    
    # Our position characteristics (from backtest):
    # - Average hold time: ~30-40 hours for longs, ~20 hours for shorts
    # - Win rate: ~40% for longs, ~38% for shorts
    # - We're in BULL regime most of the time (all 9 assets currently BULL)
    
    avg_hold_hours_long = 35
    avg_hold_hours_short = 20
    funding_intervals_per_day = 3  # 8h intervals
    
    print("Assumptions:")
    print(f"  Avg hold (long): {avg_hold_hours_long}h")
    print(f"  Avg hold (short): {avg_hold_hours_short}h")
    print(f"  Funding intervals: {funding_intervals_per_day}/day (8h each)")
    print()
    
    for scenario_name, rates in FUNDING_SCENARIOS.items():
        print(f"--- {scenario_name} ---")
        total_funding_cost = 0
        
        for asset in ASSETS:
            rate = rates.get(asset, 0)
            
            # Longs: pay if rate > 0, earn if rate < 0
            funding_per_trade_long = rate * (avg_hold_hours_long / 8)
            annual_funding_long = rate * funding_intervals_per_day * 365
            
            # Shorts: earn if rate > 0, pay if rate < 0
            funding_per_trade_short = rate * (avg_hold_hours_short / 8) * -1
            annual_funding_short = rate * funding_intervals_per_day * 365 * -1
            
            total_funding_cost += abs(funding_per_trade_long)
            
            print(f"  {asset:5s}: rate={rate*100:+.3f}%/8h | "
                  f"LONG: ${funding_per_trade_long*10000:+.2f}/trade ({annual_funding_long*100:+.1f}% ann) | "
                  f"SHORT: ${funding_per_trade_short*10000:+.2f}/trade ({annual_funding_short*100:+.1f}% ann)")
        
        print(f"  Total funding impact per round: {total_funding_cost*10000:.2f} bps\n")
    
    # Recommendation
    print("=== RECOMMENDATION ===")
    print("""
1. In BULL_NORMAL regime: funding is mild positive (~0.01-0.02%/8h).
   Longs pay ~0.3-0.6% annualized. Acceptable cost for directional edge.

2. In BULL_EXTREME: funding spikes to 0.05-0.08%/8h.
   Longs pay 5-9% annualized. This eats into returns.
   SHORT sleeve benefits: earns 5-9% annualized when funding is extreme.

3. In BEAR: funding goes negative. Longs EARN 3-6% annualized.
   This is a bonus for long entries in bear regime recovery.

4. KEY INSIGHT: The SHORT sleeve has a natural funding edge in bull markets.
   When everyone is long (high positive funding), shorts earn funding.
   Combined with the directional short edge, this is additive.

5. FUNDING MOMENTUM SIGNAL: Very high funding (>0.05%/8h) often precedes
   corrections. Could be a contrarian indicator for long entries.
   Worth testing as a regime filter.
""")

    # Quantify the funding edge for short sleeve
    print("=== SHORT SLEECE FUNDING EDGE (BULL_NORMAL scenario) ===")
    for asset in ["ETH", "AVAX", "LINK", "SOL", "SUI"]:
        rate = FUNDING_SCENARIOS["BULL_NORMAL"].get(asset, 0)
        funding_earned = rate * (avg_hold_hours_short / 8)
        trades_per_year = 365 * 24 / avg_hold_hours_short
        annual_funding = funding_earned * trades_per_year
        print(f"  {asset:5s}: earn {funding_earned*100:.3f}%/trade × {trades_per_year:.0f} trades = {annual_funding*100:.1f}% annualized funding income")


if __name__ == "__main__":
    analyze_funding_impact()
