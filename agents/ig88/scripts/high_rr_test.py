"""
High R:R Test: Can higher targets overcome friction?
=====================================================
For pairs with raw edge, test if R:R 1:3, 1:4, 1:5 can salvage profitability.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Pairs with raw edge (PF > 2.5 at 0% friction)
CANDIDATES = ['AAVE', 'ALGO', 'ARB', 'ATOM', 'MATIC', 'SNX', 'SUI']


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    bb_pct = (c - bb_lower) / (std20 * 4 + 1e-10)
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    dc_upper = pd.Series(h).rolling(20).max().values
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio, dc_upper


def get_entries(pair, c, rsi, bb_pct, atr, vol_ratio, dc_upper):
    entries = []
    
    if pair in ['AAVE', 'ARB', 'ATOM', 'MATIC', 'SUI']:
        # MR entries
        for i in range(100, len(c)):
            if rsi[i] < 20 and bb_pct[i] < 0.1 and vol_ratio[i] > 1.5:
                entries.append(('MR', i))
    elif pair in ['SNX', 'ALGO']:
        # Breakout entries
        for i in range(100, len(c)):
            if c[i] > dc_upper[i-1] and vol_ratio[i] > 2.0:
                entries.append(('BREAKOUT', i))
    
    return entries


def backtest_pair(pair, entries, c, h, l, atr, stop_atr, target_atr, max_bars, friction):
    trades = []
    for strat, idx in entries:
        entry_bar = idx + 1
        if entry_bar >= len(c) - max_bars:
            continue
        
        entry_price = c[entry_bar]
        if np.isnan(entry_price) or entry_price == 0:
            continue
        
        stop_price = entry_price - atr[entry_bar] * stop_atr
        target_price = entry_price + atr[entry_bar] * target_atr
        
        for j in range(1, max_bars + 1):
            bar = entry_bar + j
            if bar >= len(l):
                break
            if l[bar] <= stop_price:
                trades.append(-atr[entry_bar] * stop_atr / entry_price - friction)
                break
            if h[bar] >= target_price:
                trades.append(atr[entry_bar] * target_atr / entry_price - friction)
                break
        else:
            exit_price = c[min(entry_bar + max_bars, len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades)


def calc_stats(t):
    if len(t) < 5:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    if len(ls) == 0 or ls.sum() == 0:
        pf = 9.99
    else:
        pf = w.sum() / abs(ls.sum())
    return {
        'n': len(t),
        'pf': round(float(pf), 2),
        'exp': round(float(t.mean() * 100), 3),
        'wr': round(float(len(w) / len(t) * 100), 1),
    }


print("=" * 120)
print("HIGH R:R TEST: Can Higher Targets Overcome Friction?")
print(f"Friction: {FRICTION*100:.0f}%")
print("=" * 120)

# Test different R:R ratios
# Stop = 1x ATR, Target = 2x, 3x, 4x, 5x ATR
RR_CONFIGS = [
    (0.5, 1.5, 15),   # Stop 0.5 ATR, Target 1.5 ATR (1:3)
    (0.75, 2.25, 20), # Stop 0.75 ATR, Target 2.25 ATR (1:3)
    (1.0, 3.0, 25),   # Stop 1 ATR, Target 3 ATR (1:3)
    (0.75, 3.0, 25),  # Stop 0.75 ATR, Target 3 ATR (1:4)
    (0.5, 3.0, 25),   # Stop 0.5 ATR, Target 3 ATR (1:6)
]

print(f"\n{'Pair':<10}", end='')
for stop, target, bars in RR_CONFIGS:
    rr = target / stop
    print(f"S={stop:.2f} T={target:.2f} ", end='')
print()
print("-" * 100)

for pair in CANDIDATES:
    try:
        df = load_data(pair)
        c, h, l, rsi, bb_pct, atr, vol_ratio, dc_upper = compute_indicators(df)
        entries = get_entries(pair, c, rsi, bb_pct, atr, vol_ratio, dc_upper)
        
        print(f"{pair:<10}", end='')
        
        for stop, target, bars in RR_CONFIGS:
            trades = backtest_pair(pair, entries, c, h, l, atr, stop, target, bars, FRICTION)
            stats = calc_stats(trades)
            
            if stats['pf'] >= 2.0:
                print(f"\033[92mN={stats['n']:<2} PF={stats['pf']:<5.2f}\033[0m ", end='')
            elif stats['pf'] >= 1.5:
                print(f"\033[93mN={stats['n']:<2} PF={stats['pf']:<5.2f}\033[0m ", end='')
            elif stats['n'] >= 5:
                print(f"\033[91mN={stats['n']:<2} PF={stats['pf']:<5.2f}\033[0m ", end='')
            else:
                print(f"N={stats['n']:<2} {'---':<10} ", end='')
        print()
    
    except Exception as e:
        print(f"{pair:<10} ERROR: {e}")

# Optimal configuration per pair
print(f"\n{'=' * 120}")
print("OPTIMAL CONFIGURATION PER PAIR")
print("=" * 120)

optimal_configs = []

for pair in CANDIDATES:
    df = load_data(pair)
    c, h, l, rsi, bb_pct, atr, vol_ratio, dc_upper = compute_indicators(df)
    entries = get_entries(pair, c, rsi, bb_pct, atr, vol_ratio, dc_upper)
    
    best_config = None
    best_pf = 0
    
    # Grid search over more configs
    for stop in [0.5, 0.75, 1.0, 1.25]:
        for target in [1.5, 2.0, 2.5, 3.0, 4.0, 5.0]:
            for bars in [15, 20, 25, 30]:
                trades = backtest_pair(pair, entries, c, h, l, atr, stop, target, bars, FRICTION)
                stats = calc_stats(trades)
                
                if stats['n'] >= 5 and stats['pf'] > best_pf:
                    best_pf = stats['pf']
                    best_config = {
                        'pair': pair,
                        'stop': stop,
                        'target': target,
                        'bars': bars,
                        'n': stats['n'],
                        'pf': stats['pf'],
                        'exp': stats['exp'],
                        'wr': stats['wr'],
                    }
    
    if best_config:
        optimal_configs.append(best_config)

print(f"\n{'Pair':<10} {'Stop':<8} {'Target':<10} {'R:R':<8} {'Bars':<8} {'N':<6} {'PF':<8} {'Exp%':<10} {'WR%'}")
print("-" * 80)
for cfg in sorted(optimal_configs, key=lambda x: x['pf'], reverse=True):
    rr = cfg['target'] / cfg['stop']
    print(f"{cfg['pair']:<10} {cfg['stop']:<8.2f} {cfg['target']:<10.2f} 1:{rr:<5.0f} {cfg['bars']:<8} {cfg['n']:<6} {cfg['pf']:<8.2f} {cfg['exp']:<10.3f} {cfg['wr']}")

print(f"\nPairs that work at 2% friction with optimized R:R: {len([c for c in optimal_configs if c['pf'] >= 1.5])}")
print(f"Pairs that work at PF >= 2.0: {len([c for c in optimal_configs if c['pf'] >= 2.0])}")
