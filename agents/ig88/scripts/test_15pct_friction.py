"""
Test 1.5% Friction: Can Lower Friction Unlock More Pairs?
==========================================================
If execution can be optimized to 1.5%, which pairs become viable?
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

# Test all pairs at multiple friction levels
ALL_PAIRS = []
for f in sorted(DATA_DIR.glob('binance_*_USDT_240m.parquet')):
    pair = f.name.replace('binance_', '').replace('_USDT_240m.parquet', '')
    if pair not in ['BTC', 'ETH']:
        ALL_PAIRS.append(pair)

FRICTION_LEVELS = [0.01, 0.015, 0.02]


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
    bb_upper = sma20 + std20 * 2
    bb_pct = (c - bb_lower) / (bb_upper - bb_lower + 1e-10)
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio


def backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg, friction):
    entries = []
    for i in range(100, len(c) - cfg['bars']):
        if rsi[i] < cfg['rsi'] and bb_pct[i] < cfg['bb'] and vol_ratio[i] > cfg['vol']:
            entries.append(i)
    
    trades = []
    for idx in entries:
        entry_bar = idx + 1
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
        return 0
    w = t[t > 0]
    ls = t[t <= 0]
    if len(ls) == 0 or ls.sum() == 0:
        return 9.99
    return w.sum() / abs(ls.sum())


print("=" * 130)
print("FRICTION SENSITIVITY: Which Pairs Unlock at Lower Friction?")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 130)

# Optimal configs per pair (from strategy_optimization.py)
OPTIMAL_CONFIGS = {
    'AAVE':  {'rsi': 22, 'bb': 0.15, 'vol': 1.5, 'stop': 0.75, 'target': 2.00, 'bars': 15},
    'ADA':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20},
    'ALGO':  {'rsi': 25, 'bb': 0.20, 'vol': 1.2, 'stop': 0.75, 'target': 2.00, 'bars': 15},
    'ARB':   {'rsi': 18, 'bb': 0.10, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20},
    'ATOM':  {'rsi': 20, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25},
    'AVAX':  {'rsi': 20, 'bb': 0.15, 'vol': 1.2, 'stop': 1.25, 'target': 2.50, 'bars': 20},
    'DOT':   {'rsi': 25, 'bb': 0.15, 'vol': 1.5, 'stop': 0.75, 'target': 2.00, 'bars': 15},
    'FIL':   {'rsi': 25, 'bb': 0.10, 'vol': 1.5, 'stop': 0.75, 'target': 2.00, 'bars': 15},
    'GRT':   {'rsi': 25, 'bb': 0.10, 'vol': 1.2, 'stop': 0.75, 'target': 2.50, 'bars': 15},
    'IMX':   {'rsi': 25, 'bb': 0.10, 'vol': 1.5, 'stop': 0.75, 'target': 2.00, 'bars': 15},
    'INJ':   {'rsi': 20, 'bb': 0.05, 'vol': 1.5, 'stop': 1.25, 'target': 2.50, 'bars': 20},
    'LINK':  {'rsi': 18, 'bb': 0.05, 'vol': 1.8, 'stop': 1.00, 'target': 2.50, 'bars': 20},
    'LTC':   {'rsi': 25, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 2.50, 'bars': 20},
    'MATIC': {'rsi': 25, 'bb': 0.15, 'vol': 1.8, 'stop': 1.25, 'target': 2.50, 'bars': 20},
    'NEAR':  {'rsi': 20, 'bb': 0.10, 'vol': 1.5, 'stop': 1.00, 'target': 2.50, 'bars': 20},
    'OP':    {'rsi': 20, 'bb': 0.10, 'vol': 1.5, 'stop': 1.00, 'target': 2.50, 'bars': 20},
    'POL':   {'rsi': 20, 'bb': 0.10, 'vol': 1.5, 'stop': 1.00, 'target': 2.50, 'bars': 20},
    'SOL':   {'rsi': 18, 'bb': 0.10, 'vol': 1.5, 'stop': 1.00, 'target': 2.00, 'bars': 15},
    'SNX':   {'rsi': 25, 'bb': 0.10, 'vol': 1.5, 'stop': 0.75, 'target': 2.50, 'bars': 15},
    'SUI':   {'rsi': 18, 'bb': 0.05, 'vol': 1.2, 'stop': 1.00, 'target': 3.00, 'bars': 25},
    'UNI':   {'rsi': 22, 'bb': 0.10, 'vol': 1.8, 'stop': 0.75, 'target': 2.00, 'bars': 15},
    'XRP':   {'rsi': 25, 'bb': 0.10, 'vol': 1.5, 'stop': 1.00, 'target': 2.50, 'bars': 20},
}

print(f"\n{'Pair':<10}", end='')
for f in FRICTION_LEVELS:
    print(f"F={f*100:.1f}%{'':<10}", end='')
print("  Unlock @ 1.5%")
print("-" * 90)

unlock_at_15 = []

for pair, cfg in OPTIMAL_CONFIGS.items():
    if pair not in ALL_PAIRS:
        continue
    
    df = load_data(pair)
    c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)
    
    pfs = {}
    for friction in FRICTION_LEVELS:
        trades = backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg, friction)
        pfs[friction] = calc_pf(trades)
    
    print(f"{pair:<10}", end='')
    for friction in FRICTION_LEVELS:
        pf = pfs[friction]
        if pf >= 2.0:
            print(f"\033[92m{pf:>6.2f}\033[0m{'':<8}", end='')
        elif pf >= 1.5:
            print(f"\033[93m{pf:>6.2f}\033[0m{'':<8}", end='')
        else:
            print(f"{pf:>6.2f}{'':<8}", end='')
    
    # Check if unlocks at 1.5%
    pf_15 = pfs[0.015]
    pf_20 = pfs[0.02]
    
    if pf_15 >= 1.5 and pf_20 < 1.5:
        print(f"  \033[92mUNLOCKS\033[0m")
        unlock_at_15.append((pair, pf_15, cfg))
    elif pf_15 >= 1.5:
        print(f"  viable")
    else:
        print()

# Summary
print(f"\n{'=' * 130}")
print(f"PAIRS THAT UNLOCK AT 1.5% FRICTION: {len(unlock_at_15)}")
print("=" * 130)

if unlock_at_15:
    print(f"\n{'Pair':<10} {'PF@1.5%':<12} {'Size':<10} {'Stop':<10} {'Target':<12} {'R:R'}")
    print("-" * 70)
    for pair, pf, cfg in sorted(unlock_at_15, key=lambda x: x[1], reverse=True):
        rr = cfg['target'] / cfg['stop']
        print(f"{pair:<10} {pf:<12.2f} 1.0%       {cfg['stop']:<10.2f} {cfg['target']:<12.2f} 1:{rr:.0f}")

print(f"\nPRACTICAL IMPLICATION:")
print(f"If we can reduce execution friction to 1.5%, we can add {len(unlock_at_15)} more pairs.")
print(f"This might be achievable through limit orders or better execution routing.")
