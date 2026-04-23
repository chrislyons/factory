#!/usr/bin/env python3
"""
Polymarket Edge Analysis — Wolf Hour + Markov Chain
Uses Gamma API for market data, CLOB for real-time prices.
"""
import json, os, sys, time, requests
from datetime import datetime, timezone
from collections import defaultdict
import numpy as np

BASE = "/Users/nesbitt/dev/factory/agents/ig88"
DATA_DIR = os.path.join(BASE, "data", "polymarket")
os.makedirs(DATA_DIR, exist_ok=True)

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"

# ============================================================
# PART 1: Fetch all active markets with price data
# ============================================================
print("=" * 60)
print("PART 1: Fetching active markets from Gamma API")
print("=" * 60)

r = requests.get(f"{GAMMA_API}/markets", params={
    "active": "true", "closed": "false", "limit": 100
})
markets = r.json()
print(f"Got {len(markets)} active markets")

# Filter to markets with decent liquidity (> $10K)
good_markets = []
for m in markets:
    liq = float(m.get("liquidity", 0) or 0)
    if liq > 10000:
        good_markets.append(m)

print(f"{len(good_markets)} markets with liquidity > $10K")

# ============================================================
# PART 2: Wolf Hour Analysis — Spread by UTC Hour
# ============================================================
print("\n" + "=" * 60)
print("PART 2: Wolf Hour — Spread Analysis by UTC Hour")
print("=" * 60)

# Polymarket Gamma API has a /markets endpoint with historical data
# Let's try to get trade history for a few high-liquidity markets
# The trade history shows timestamps and prices

def get_market_trades(condition_id, limit=500):
    """Get recent trades for a market from the CLOB trades endpoint (public)."""
    url = f"{CLOB_API}/trades"
    r = requests.get(url, params={"market": condition_id, "limit": limit})
    if r.status_code == 200:
        return r.json().get("data", [])
    return []

# Test with a high-liquidity market
test_market = None
for m in good_markets:
    cid = m.get("conditionId") or m.get("condition_id")
    if cid:
        test_market = m
        break

if test_market:
    cid = test_market.get("conditionId") or test_market.get("condition_id")
    q = test_market.get("question", "")[:60]
    print(f"\nFetching trades for: {q}")
    trades = get_market_trades(cid, limit=500)
    print(f"Got {len(trades)} trades")

    if trades:
        print(f"Sample: {json.dumps(trades[0], indent=2)[:500]}")

# ============================================================
# PART 3: Wolf Hour — Simulated Analysis
# ============================================================
print("\n" + "=" * 60)
print("PART 3: Wolf Hour — Hypothetical Backtest")
print("=" * 60)

# Wolf Hour thesis: spreads widen during Asian hours (3-9 AM UTC)
# Strategy: buy during wide spread hours, sell when spread compresses
# Edge = spread compression profit - fees

# From TX260413: "Buy at $0.41 during Asian hours, sell at $0.50 when London opens"
# This implies ~9% edge on that trade

# Simulate with realistic parameters
np.random.seed(42)
n_simulations = 10000
n_trades_per_sim = 200  # ~10 months of trading

# Spread dynamics based on published data:
# - Normal spread: 2-5 cents on liquid markets
# - Wolf Hour spread: 8-15 cents during 3-9 AM UTC
# - Compression profit: spread_narrow / spread_wide
fees = 0.0156  # 1.56% taker fee (worst case)
edge_per_trade = 0.03  # 3% net edge after fees (conservative vs 9% published)
edge_std = 0.08  # standard deviation of per-trade returns

equity_curves = []
for _ in range(n_simulations):
    returns = np.random.normal(edge_per_trade, edge_std, n_trades_per_sim)
    equity = np.cumprod(1 + returns)
    equity_curves.append(equity)

# Statistics
final_equities = [ec[-1] for ec in equity_curves]
median_equity = np.median(final_equities)
p5_equity = np.percentile(final_equities, 5)
p95_equity = np.percentile(final_equities, 95)
mean_pf = np.mean([np.sum(r[r>0]) / (np.abs(np.sum(r[r<=0])) or 0.001) for r in
                   [np.random.normal(edge_per_trade, edge_std, n_trades_per_sim) for _ in range(100)]])

print(f"Wolf Hour Hypothetical (n={n_trades_per_sim} trades, edge={edge_per_trade*100:.0f}% per trade)")
print(f"  Median equity: {median_equity:.2f}x ({(median_equity-1)*100:.0f}% return)")
print(f"  P5 equity:     {p5_equity:.2f}x ({(p5_equity-1)*100:.0f}% return)")
print(f"  P95 equity:    {p95_equity:.2f}x ({(p95_equity-1)*100:.0f}% return)")
print(f"  Avg PF:        {mean_pf:.2f}")
print(f"  Win rate:      {np.mean([np.mean(r>0) for r in [np.random.normal(edge_per_trade, edge_std, 50) for _ in range(100)]])*100:.0f}%")

# Annualized estimate
n_years = n_trades_per_sim / 200  # ~200 trades per year
ann = median_equity ** (1/n_years) - 1
print(f"  Annualized (median): {ann*100:.0f}%")

# ============================================================
# PART 4: Markov Chain — Transition Matrix Analysis
# ============================================================
print("\n" + "=" * 60)
print("PART 4: Markov Chain — Transition Matrix")
print("=" * 60)

# Markov Chain thesis: prediction market prices transition between states
# with predictable probabilities
# States: "Very Low" (<0.2), "Low" (0.2-0.4), "Mid" (0.4-0.6), "High" (0.6-0.8), "Very High" (>0.8)

# Generate synthetic transition data based on published results:
# "3 accounts all profited $1M+/month using Markov chains"
# This implies high-accuracy state prediction

states = ["VL", "L", "M", "H", "VH"]
state_ranges = [(0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0)]

# Transition matrix (rows=from, cols=to)
# Based on typical prediction market dynamics:
# - Prices tend toward 0 or 1 (resolution)
# - Mid-range prices (0.4-0.6) are the most volatile
# - Extreme prices (near 0 or 1) are stickier
transition_matrix = np.array([
    #  VL    L     M     H     VH   (to)
    [0.85, 0.10, 0.04, 0.01, 0.00],  # from VL
    [0.15, 0.60, 0.20, 0.04, 0.01],  # from L
    [0.05, 0.20, 0.50, 0.20, 0.05],  # from M
    [0.01, 0.04, 0.20, 0.60, 0.15],  # from H
    [0.00, 0.01, 0.04, 0.10, 0.85],  # from VH
])

print("Transition Matrix (probability of moving from state i to state j):")
print(f"  {'':>4s}", end="")
for s in states:
    print(f"  {s:>5s}", end="")
print()

for i, s in enumerate(states):
    print(f"  {s:>4s}", end="")
    for j in range(len(states)):
        print(f"  {transition_matrix[i][j]:5.2f}", end="")
    print()

# Steady-state distribution
eigenvalues, eigenvectors = np.linalg.eig(transition_matrix.T)
steady_state = eigenvectors[:, np.argmax(eigenvalues)].real
steady_state = steady_state / steady_state.sum()
print(f"\nSteady-state distribution: {dict(zip(states, steady_state.round(3)))}")

# Markov Chain trading simulation
# Strategy: if current state predicts next state with >60% probability, trade that direction
print("\nMarkov Chain Trading Simulation (n=1000 market-day periods):")
n_mc_sims = 1000
n_periods = 250  # ~1 year
mc_returns = []

for _ in range(n_mc_sims):
    current_state = 2  # Start in Middle
    period_return = 0
    for __ in range(n_periods):
        probs = transition_matrix[current_state]
        predicted_next = np.argmax(probs)
        confidence = probs[predicted_next]

        if confidence > 0.6 and predicted_next != current_state:
            # Trade: buy if moving up, sell if moving down
            direction = 1 if predicted_next > current_state else -1
            actual_next = np.random.choice(5, p=probs)
            correct = (actual_next == predicted_next)
            if correct:
                period_return += confidence * 0.02  # Win
            else:
                period_return -= 0.02  # Loss
        current_state = predicted_next
    mc_returns.append(period_return)

mc_median = np.median(mc_returns)
mc_p5 = np.percentile(mc_returns, 5)
mc_p95 = np.percentile(mc_returns, 95)
wr = np.mean([r > 0 for r in mc_returns]) * 100

print(f"  Median return (1yr): {mc_median*100:.0f}%")
print(f"  P5 return:           {mc_p5*100:.0f}%")
print(f"  P95 return:          {mc_p95*100:.0f}%")
print(f"  Profitable sims:     {wr:.0f}%")

# ============================================================
# PART 5: Summary & Recommendations
# ============================================================
print("\n" + "=" * 60)
print("PART 5: Summary — Edge Viability Assessment")
print("=" * 60)

results = {
    "wolf_hour": {
        "median_ann_return": round(ann * 100, 0),
        "p5_return": round((p5_equity - 1) * 100, 0),
        "p95_return": round((p95_equity - 1) * 100, 0),
        "trades_per_year": 200,
        "edge_per_trade_pct": edge_per_trade * 100,
        "verdict": "NEEDS LIVE DATA — spread widening must be confirmed with historical data",
        "data_required": "Intraday trade timestamps + prices from Polymarket CLOB or Gamma API",
        "status": "PRELIMINARY"
    },
    "markov_chain": {
        "median_ann_return": round(mc_median * 100, 0),
        "profitable_pct": round(wr, 0),
        "trades_per_year": 250,
        "states": states,
        "verdict": "NEEDS HISTORICAL DATA — transition matrix must be trained on real price data",
        "data_required": "Historical price time-series per market (Gamma API or Jon Becker dataset)",
        "status": "PRELIMINARY"
    }
}

print(json.dumps(results, indent=2))

with open(os.path.join(DATA_DIR, "edge_analysis.json"), "w") as f:
    json.dump(results, f, indent=2)
print(f"\nSaved to {os.path.join(DATA_DIR, 'edge_analysis.json')}")
