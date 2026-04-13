#!/usr/bin/env python3
"""
Pair-Specific R:R Optimization
================================
Find optimal Stop/Target for each pair.
Our current configs might be suboptimal.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
import json

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.01

CURRENT_CONFIG = {
    'ARB':   {'rsi': 18, 'bb': 0.10, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 2.5},
    'SUI':   {'rsi': 18, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25, 'size': 2.5},
    'AVAX':  {'rsi': 20, 'bb': 0.15, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 2.5},
    'MATIC': {'rsi': 25, 'bb': 0.15, 'vol': 1.8, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 2.5},
    'UNI':   {'rsi': 22, 'bb': 0.10, 'vol': 1.8, 'stop': 0.75, 'target': 2.00, 'bars': 15, 'size': 2.0},
    'DOT':   {'rsi': 20, 'bb': 0.10, 'vol': 1.0, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.5},
    'ALGO':  {'rsi': 25, 'bb': 0.20, 'vol': 1.2, 'stop': 0.75, 'target': 2.00, 'bars': 15, 'size': 1.5},
    'ATOM':  {'rsi': 20, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25, 'size': 1.5},
    'FIL':   {'rsi': 20, 'bb': 0.10, 'vol': 1.0, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.5},
    'ADA':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 1.0},
    'INJ':   {'rsi': 20, 'bb': 0.05, 'vol': 1.5, 'stop': 1.25, 'target': 2.50, 'bars': 20, 'size': 1.0},
    'LINK':  {'rsi': 18, 'bb': 0.05, 'vol': 1.8, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.0},
    'LTC':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.0},
    'AAVE':  {'rsi': 22, 'bb': 0.15, 'vol': 1.5, 'stop': 0.75, 'target': 2.00, 'bars': 15, 'size': 1.0},
    'SNX':   {'rsi': 22, 'bb': 0.10, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20, 'size': 1.0},
}


def load_data(pair):
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if path.exists():
        return pd.read_parquet(path)
    return None


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
    bb_pct = (c - (sma20 - std20 * 2)) / (std20 * 4 + 1e-10)
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio


def backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg, friction=FRICTION):
    entries = []
    for i in range(100, len(c) - cfg['bars']):
        if rsi[i] < cfg['rsi'] and bb_pct[i] < cfg['bb'] and vol_ratio[i] > cfg['vol']:
            entries.append(i)
    
    trades = []
    for idx in entries:
        entry_bar = idx + 1
        if entry_bar >= len(c) - cfg['bars']:
            continue
        
        entry_price = c[entry_bar]
        if np.isnan(entry_price) or entry_price == 0:
            continue
        
        stop_price = entry_price - atr[entry_bar] * cfg['stop']
        target_price = entry_price + atr[entry_bar] * cfg['target']
        
        for j in range(1, cfg['bars'] + 1):
            bar = entry_bar + j
            if bar >= len(l):
                break
            if l[bar] <= stop_price:
                trades.append(-atr[entry_bar] * cfg['stop'] / entry_price - friction)
                break
            if h[bar] >= target_price:
                trades.append(atr[entry_bar] * cfg['target'] / entry_price - friction)
                break
        else:
            exit_price = c[min(entry_bar + cfg['bars'], len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades)


def calc_pf(t):
    if len(t) < 5:
        return -999
    w = t[t > 0]
    ls = t[t <= 0]
    if len(ls) == 0 or ls.sum() == 0:
        return 9.99
    return w.sum() / abs(ls.sum())


def optimize_pair(pair, df, current_cfg):
    c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)
    
    # Fixed entry params
    rsi_t = current_cfg['rsi']
    bb_t = current_cfg['bb']
    vol_t = current_cfg['vol']
    
    best_config = None
    best_score = -999
    
    # Grid search over R:R parameters
    for stop in [0.50, 0.75, 1.00, 1.25, 1.50]:
        for target in [1.50, 2.00, 2.50, 3.00, 4.00]:
            for bars in [15, 20, 25, 30]:
                cfg = {
                    'rsi': rsi_t, 'bb': bb_t, 'vol': vol_t,
                    'stop': stop, 'target': target, 'bars': bars
                }
                
                trades = backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg)
                
                if len(trades) < 8:
                    continue
                
                pf = calc_pf(trades)
                exp = trades.mean() * 100
                
                # Score: PF weighted by sample size and expectancy
                if pf >= 1.5 and exp > 0:
                    score = pf * np.log(len(trades)) * exp
                    
                    if score > best_score:
                        best_score = score
                        best_config = {
                            'stop': stop, 'target': target, 'bars': bars,
                            'pf': pf, 'exp': exp, 'n': len(trades),
                            'wr': (trades > 0).sum() / len(trades) * 100
                        }
    
    return best_config


print("=" * 100)
print("PAIR-SPECIFIC R:R OPTIMIZATION")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 100)

print(f"\n{'Pair':<10} {'Current R:R':<15} {'Optimized R:R':<15} {'Current PF':<12} {'Opt PF':<12} {'N'}")
print("-" * 90)

optimized = {}

for pair, current in CURRENT_CONFIG.items():
    df = load_data(pair)
    if df is None:
        print(f"{pair:<10} NO DATA")
        continue
    
    # Current performance
    c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)
    current_trades = backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, current)
    current_pf = calc_pf(current_trades) if len(current_trades) >= 5 else 0
    current_rr = f"1:{current['target']/current['stop']:.1f}"
    
    # Optimize
    best = optimize_pair(pair, df, current)
    
    if best:
        opt_rr = f"1:{best['target']/best['stop']:.1f}"
        optimized[pair] = best
        
        # Calculate improvement
        if best['pf'] > current_pf:
            status = "\033[92m+\033[0m"
        elif best['pf'] < current_pf:
            status = "\033[91m-\033[0m"
        else:
            status = "="
        
        print(f"{pair:<10} {current_rr:<15} {opt_rr:<15} {current_pf:<12.2f} {status} {best['pf']:.2f}  {best['n']}")
    else:
        print(f"{pair:<10} {current_rr:<15} {'NO EDGE':<15} {current_pf:<12.2f}")

print(f"\n{'=' * 100}")
print("OPTIMIZED CONFIGS")
print("=" * 100)

# Save optimized configs
final_configs = {}
for pair in CURRENT_CONFIG:
    if pair in optimized:
        opt = optimized[pair]
        final_configs[pair] = {
            **CURRENT_CONFIG[pair],
            'stop': opt['stop'],
            'target': opt['target'],
            'bars': opt['bars'],
            'opt_pf': round(opt['pf'], 2),
            'opt_exp': round(opt['exp'], 3),
        }

print(json.dumps(final_configs, indent=2))

# Save to file
with open(DATA_DIR / 'optimized_rr.json', 'w') as f:
    json.dump(final_configs, f, indent=2)
print(f"\nSaved to {DATA_DIR / 'optimized_rr.json'}")
