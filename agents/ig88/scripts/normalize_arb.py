"""
Normalize ARB: Is the edge just from deeper BB signals?
========================================================
Test: If we filter other pairs to same BB depth as ARB, do they match?
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

PAIRS = ['ARB', 'AVAX', 'AAVE', 'SUI', 'ATOM']


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    bb_dist = (c - bb_lower) / c * 100  # How far below BB
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, o, h, l, rsi, bb_lower, bb_dist, atr, vol_ratio


def run_mr_filtered(c, o, h, l, rsi, bb_lower, bb_dist, atr, vol_ratio, 
                    min_bb_dist=None, min_rsi=None):
    """Run MR with additional filters."""
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
            continue
        
        # Standard filters
        if rsi[i] >= 20:
            continue
        if c[i] >= bb_lower[i]:
            continue
        if vol_ratio[i] <= 1.5:
            continue
        
        # Additional filters for normalization
        if min_bb_dist is not None and bb_dist[i] > min_bb_dist:
            continue  # Skip if BB distance is too shallow (want deeper)
        if min_rsi is not None and rsi[i] < min_rsi:
            continue  # Skip if RSI is too low (optional)
        
        entry_bar = i + 2
        if entry_bar >= len(c) - 15:
            continue
        entry_price = o[entry_bar]
        stop_price = entry_price - atr[entry_bar] * 0.75
        target_price = entry_price + atr[entry_bar] * 2.5
        
        for j in range(1, 15):
            bar = entry_bar + j
            if bar >= len(l): break
            if l[bar] <= stop_price:
                trades.append(-atr[entry_bar] * 0.75 / entry_price - FRICTION)
                break
            if h[bar] >= target_price:
                trades.append(atr[entry_bar] * 2.5 / entry_price - FRICTION)
                break
        else:
            exit_price = c[min(entry_bar + 15, len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades)


def calc_stats(t):
    if len(t) < 3:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean()*100), 3), 'wr': round(float(len(w)/len(t)*100), 1)}


print("=" * 120)
print("NORMALIZE ARB: Is the edge from deeper BB signals?")
print("=" * 120)

# First, get ARB's BB distribution
print("\nSTEP 1: BB Distance Distribution at Signal")
print("-" * 60)

arb_df = load_data('ARB')
arb_c, arb_o, arb_h, arb_l, arb_rsi, arb_bb, arb_bb_dist, arb_atr, arb_vol = compute_indicators(arb_df)

# Get ARB's BB distances at signals
arb_signal_bbdists = []
for i in range(100, len(arb_c) - 15):
    if arb_rsi[i] < 20 and arb_c[i] < arb_bb[i] and arb_vol[i] > 1.5:
        arb_signal_bbdists.append(arb_bb_dist[i])

arb_signal_bbdists = np.array(arb_signal_bbdists)
print(f"ARB signal BB distances:")
print(f"  Mean: {arb_signal_bbdists.mean():.2f}%")
print(f"  Median: {np.median(arb_signal_bbdists):.2f}%")
print(f"  Std: {arb_signal_bbdists.std():.2f}%")
print(f"  25th pctl: {np.percentile(arb_signal_bbdists, 25):.2f}%")
print(f"  75th pctl: {np.percentile(arb_signal_bbdists, 75):.2f}%")

# Now test: filter other pairs to ARB's BB depth
print(f"\n{'=' * 120}")
print("STEP 2: Performance at Different BB Depths")
print(f"{'=' * 120}")

print(f"\n{'Pair':<8} {'Unfiltered':<20} {'BB<-5%':<20} {'BB<-6%':<20} {'BB<-7%'}")
print("-" * 80)

for pair in PAIRS:
    df = load_data(pair)
    c, o, h, l, rsi, bb_lower, bb_dist, atr, vol_ratio = compute_indicators(df)
    
    # Unfiltered
    trades = run_mr_filtered(c, o, h, l, rsi, bb_lower, bb_dist, atr, vol_ratio)
    stats = calc_stats(trades)
    
    # BB < -5%
    trades_5 = run_mr_filtered(c, o, h, l, rsi, bb_lower, bb_dist, atr, vol_ratio, min_bb_dist=-5)
    stats_5 = calc_stats(trades_5)
    
    # BB < -6%
    trades_6 = run_mr_filtered(c, o, h, l, rsi, bb_lower, bb_dist, atr, vol_ratio, min_bb_dist=-6)
    stats_6 = calc_stats(trades_6)
    
    # BB < -7%
    trades_7 = run_mr_filtered(c, o, h, l, rsi, bb_lower, bb_dist, atr, vol_ratio, min_bb_dist=-7)
    stats_7 = calc_stats(trades_7)
    
    print(f"{pair:<8} "
          f"N={stats['n']:<2} {stats['exp']:>5.2f}% PF={stats['pf']:<5.2f}  "
          f"N={stats_5['n']:<2} {stats_5['exp']:>5.2f}% PF={stats_5['pf']:<5.2f}  "
          f"N={stats_6['n']:<2} {stats_6['exp']:>5.2f}% PF={stats_6['pf']:<5.2f}  "
          f"N={stats_7['n']:<2} {stats_7['exp']:>5.2f}% PF={stats_7['pf']:<5.2f}")

# Test: What if we use RSI threshold instead?
print(f"\n{'=' * 120}")
print("STEP 3: Test with RSI < 18 (deeper oversold)")
print(f"{'=' * 120}")

print(f"\n{'Pair':<8} {'RSI<20':<20} {'RSI<18':<20} {'RSI<15'}")
print("-" * 60)

for pair in PAIRS:
    df = load_data(pair)
    c, o, h, l, rsi, bb_lower, bb_dist, atr, vol_ratio = compute_indicators(df)
    
    # RSI < 20 (standard)
    trades_20 = run_mr_filtered(c, o, h, l, rsi, bb_lower, bb_dist, atr, vol_ratio)
    stats_20 = calc_stats(trades_20)
    
    # RSI < 18
    trades_18 = run_mr_filtered(c, o, h, l, rsi, bb_lower, bb_dist, atr, vol_ratio, min_rsi=18)
    stats_18 = calc_stats(trades_18)
    
    # RSI < 15
    trades_15 = run_mr_filtered(c, o, h, l, rsi, bb_lower, bb_dist, atr, vol_ratio, min_rsi=15)
    stats_15 = calc_stats(trades_15)
    
    print(f"{pair:<8} "
          f"N={stats_20['n']:<3} {stats_20['exp']:>5.2f}% PF={stats_20['pf']:<5.2f}  "
          f"N={stats_18['n']:<3} {stats_18['exp']:>5.2f}% PF={stats_18['pf']:<5.2f}  "
          f"N={stats_15['n']:<3} {stats_15['exp']:>5.2f}% PF={stats_15['pf']:<5.2f}")

# Final conclusion
print(f"\n{'=' * 120}")
print("CONCLUSION")
print(f"{'=' * 120}")

print("""
If filtering other pairs to ARB's BB depth makes them perform similarly,
then ARB's edge is just from deeper signals (not a special property of ARB).

If they still don't match, then ARB has a genuine structural advantage
(market microstructure, liquidity, or price behavior).
""")
