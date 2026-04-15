"""
Friction Analysis: Maximum Tolerable Cost-Per-Trade
====================================================
1. Verify all tests included 0.25% perps friction
2. Determine breakeven cost-per-trade for each pair/strategy
3. Find the maximum tolerable cost across the portfolio

Cost-per-trade = Entry fee + Exit fee + Slippage
For Jupiter Perps: 0.05% maker + 0.05% taker per side = 0.1% round-trip minimum
With borrowing fees: 0.25%+ round-trip is realistic
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
BASE_FRICTION = 0.0025  # 0.25% — what we've been using


def load_data(pair):
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    return pd.read_parquet(path) if path.exists() else None


def compute_indicators(df):
    c = df['close'].values
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14).mean()
    rsi = (100 - (100 / (1 + gain / loss))).values
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    vol_sma = df['volume'].rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    h, l = df['high'].values, df['low'].values
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # BTC regime
    btc_df = load_data('BTC')
    btc_c = btc_df['close'].values
    btc_20ret = np.full(len(c), np.nan)
    btc_ret = pd.Series(btc_c).pct_change(20).values
    min_len = min(len(btc_ret), len(c))
    btc_20ret[:min_len] = btc_ret[:min_len]
    
    return {
        'c': c, 'o': df['open'].values, 'h': h, 'l': l,
        'rsi': rsi, 'sma20': sma20, 'std20': std20,
        'vol_ratio': vol_ratio, 'atr': atr, 'btc_20ret': btc_20ret,
    }


# Optimized params per pair (from robustness audit)
MR_PARAMS = {
    'SOL':  {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 1, 'stop': 0.005, 'target': 0.10},
    'NEAR': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.125},
    'LINK': {'rsi': 30, 'bb': 2.0, 'vol': 1.8, 'entry': 1, 'stop': 0.005, 'target': 0.15},
    'AVAX': {'rsi': 30, 'bb': 1.5, 'vol': 1.8, 'entry': 2, 'stop': 0.005, 'target': 0.125},
}


def run_backtest_mr(ind, params, friction):
    """Run MR backtest with specified friction."""
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    rsi, sma20, std20, vol_ratio = ind['rsi'], ind['sma20'], ind['std20'], ind['vol_ratio']
    bb_l = sma20 - std20 * params['bb']
    
    trades = []
    for i in range(100, len(c) - params['entry'] - 8):
        if np.isnan(rsi[i]) or np.isnan(bb_l[i]) or np.isnan(vol_ratio[i]):
            continue
        if rsi[i] < params['rsi'] and c[i] < bb_l[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + params['entry']
            if entry_bar >= len(c) - 8:
                continue
            entry_price = o[entry_bar]
            stop_price = entry_price * (1 - params['stop'])
            target_price = entry_price * (1 + params['target'])
            
            for j in range(1, 9):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-params['stop'] - friction)
                    break
                if h[bar] >= target_price:
                    trades.append(params['target'] - friction)
                    break
            else:
                exit_price = c[min(entry_bar + 8, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades) if trades else np.array([])


def calc_expectancy(trades):
    """Return expectancy per trade as a percentage."""
    if len(trades) < 5:
        return None
    return float(trades.mean() * 100)


print("=" * 100)
print("FRICTION ANALYSIS: MAXIMUM TOLERABLE COST-PER-TRADE")
print("=" * 100)

# ============================================================================
# PART 1: Verify current friction application
# ============================================================================
print("\n" + "=" * 80)
print("PART 1: FRICTION VERIFICATION")
print("=" * 80)

print(f"\nCurrent friction applied in all backtests: {BASE_FRICTION*100:.2f}%")
print(f"This represents: Entry fee + Exit fee + Estimated slippage")
print(f"\nJupiter Perps fee structure:")
print(f"  - Taker fee: 0.05% per side")
print(f"  - Maker fee: 0.03% per side")
print(f"  - Round-trip (taker+taker): 0.10%")
print(f"  - With borrowing fees: ~0.25% round-trip (our assumption)")

# ============================================================================
# PART 2: Breakeven Cost-Per-Trade Analysis
# ============================================================================
print("\n" + "=" * 80)
print("PART 2: BREAKEVEN COST-PER-TRADE BY PAIR")
print("=" * 80)

print(f"\n{'Pair':<10} {'Gross Exp%':<15} {'Friction':<12} {'Net Exp%':<12} {'Breakeven':<12} {'N'}")
print("-" * 75)

breakeven_results = {}

for pair in ['SOL', 'NEAR', 'LINK', 'AVAX']:
    df = load_data(pair)
    if df is None:
        continue
    
    ind = compute_indicators(df)
    params = MR_PARAMS[pair]
    
    # Run with ZERO friction to get gross expectancy
    trades_gross = run_backtest_mr(ind, params, friction=0.0)
    gross_exp = calc_expectancy(trades_gross)
    
    # Run with BASE friction to verify
    trades_net = run_backtest_mr(ind, params, friction=BASE_FRICTION)
    net_exp = calc_expectancy(trades_net)
    
    # Calculate implied friction
    implied_friction = gross_exp - net_exp if gross_exp and net_exp else None
    
    # Breakeven is where net expectancy = 0
    # So breakeven friction = gross expectancy
    breakeven = gross_exp  # In percent
    
    breakeven_results[pair] = {
        'gross_exp': gross_exp,
        'net_exp': net_exp,
        'implied_friction': implied_friction,
        'breakeven': breakeven,
        'n': len(trades_gross),
    }
    
    print(f"{pair:<10} {gross_exp:>10.3f}%   {implied_friction:>8.3f}%   {net_exp:>8.3f}%   {breakeven:>8.3f}%   {len(trades_gross)}")

# ============================================================================
# PART 3: Maximum Tolerable Cost-Per-Trade (Sensitivity Analysis)
# ============================================================================
print("\n" + "=" * 80)
print("PART 3: COST-PER-TRADE SENSITIVITY")
print("At what total cost does each pair become unprofitable?")
print("=" * 80)

cost_levels = [0.001, 0.0015, 0.002, 0.0025, 0.003, 0.0035, 0.004, 0.005, 0.006, 0.0075, 0.01]

print(f"\n{'Pair':<10}", end='')
for cost in cost_levels:
    print(f"{cost*100:>6.2f}%", end='')
print("  MaxSafe")
print("-" * 95)

for pair in ['SOL', 'NEAR', 'LINK', 'AVAX']:
    df = load_data(pair)
    ind = compute_indicators(df)
    params = MR_PARAMS[pair]
    
    print(f"{pair:<10}", end='')
    
    max_safe = 0
    for cost in cost_levels:
        trades = run_backtest_mr(ind, params, friction=cost)
        exp = calc_expectancy(trades)
        
        if exp is None:
            print(f"{'  N/A':>7}", end='')
        elif exp > 0:
            print(f"{'  ✓':>6}", end='')
            max_safe = cost
        else:
            print(f"{'  ✗':>6}", end='')
    
    print(f"  {max_safe*100:.2f}%")

# ============================================================================
# PART 4: Portfolio-Level Breakeven
# ============================================================================
print("\n" + "=" * 80)
print("PART 4: PORTFOLIO-LEVEL BREAKEVEN ANALYSIS")
print("=" * 80)

# Calculate weighted average expectancy
total_trades = 0
weighted_gross = 0
weighted_net = 0

for pair, r in breakeven_results.items():
    weighted_gross += r['gross_exp'] * r['n']
    weighted_net += r['net_exp'] * r['n']
    total_trades += r['n']

if total_trades > 0:
    portfolio_gross = weighted_gross / total_trades
    portfolio_net = weighted_net / total_trades
    portfolio_breakeven = portfolio_gross
    
    print(f"\nPortfolio (weighted by trade count):")
    print(f"  Total trades: {total_trades}")
    print(f"  Gross expectancy: {portfolio_gross:.3f}%")
    print(f"  Net expectancy (at 0.25% friction): {portfolio_net:.3f}%")
    print(f"  Breakeven cost-per-trade: {portfolio_breakeven:.3f}%")
    print(f"  Current cost (0.25%): {'SAFE' if 0.0025 < portfolio_breakeven else 'UNSAFE'}")
    
    # Recommended maximum
    recommended_max = portfolio_breakeven * 0.6  # 60% of breakeven for safety margin
    print(f"\n  RECOMMENDED MAXIMUM COST-PER-TRADE: {recommended_max:.2f}%")
    print(f"  (60% of breakeven for safety margin)")

# ============================================================================
# PART 5: Friction Component Breakdown
# ============================================================================
print("\n" + "=" * 80)
print("PART 5: FRICTION COMPONENT BREAKDOWN")
print("=" * 80)

print("""
For Jupiter Perps (realistic):
┌─────────────────────────────────────────────────────────────────┐
│ Component              │ Minimum    │ Realistic  │ Worst Case  │
├─────────────────────────────────────────────────────────────────┤
│ Taker fee (per side)   │ 0.05%      │ 0.05%      │ 0.07%       │
│ Round-trip taker       │ 0.10%      │ 0.10%      │ 0.14%       │
│ Borrowing fee (perp)   │ 0.01%      │ 0.05%      │ 0.20%       │
│ Slippage (per side)    │ 0.02%      │ 0.05%      │ 0.15%       │
│ Round-trip slippage    │ 0.04%      │ 0.10%      │ 0.30%       │
├─────────────────────────────────────────────────────────────────┤
│ TOTAL ROUND-TRIP       │ 0.15%      │ 0.25%      │ 0.64%       │
└─────────────────────────────────────────────────────────────────┘

Key insight: During high-volatility periods (when MR triggers),
slippage can spike significantly. The 0.25% assumption is optimistic.
""")

# ============================================================================
# PART 6: Stress Test — What if friction doubles?
# ============================================================================
print("=" * 80)
print("PART 6: STRESS TEST — FRICTION DOUBLING SCENARIO")
print("=" * 80)

print(f"\n{'Pair':<10} {'@0.25%':<12} {'@0.50%':<12} {'Degradation':<15} {'Still Profitable?'}")
print("-" * 70)

for pair in ['SOL', 'NEAR', 'LINK', 'AVAX']:
    df = load_data(pair)
    ind = compute_indicators(df)
    params = MR_PARAMS[pair]
    
    t1 = run_backtest_mr(ind, params, friction=0.0025)
    t2 = run_backtest_mr(ind, params, friction=0.005)
    
    e1 = calc_expectancy(t1)
    e2 = calc_expectancy(t2)
    
    if e1 and e2:
        degradation = ((e2 - e1) / abs(e1)) * 100 if e1 != 0 else 0
        still_profitable = "YES" if e2 > 0 else "NO"
        print(f"{pair:<10} {e1:>8.3f}%   {e2:>8.3f}%   {degradation:>10.1f}%     {still_profitable}")

print("\n" + "=" * 100)
print("CONCLUSION: MAXIMUM TOLERABLE COST-PER-TRADE")
print("=" * 100)
