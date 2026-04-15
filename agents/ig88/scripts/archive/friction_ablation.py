"""
Friction Ablation: Which Strategies Survive At Different Friction Levels?
==========================================================================
Test at 0%, 0.5%, 1%, 1.5%, 2% friction to find:
1. Which pairs have RAW edge (profitable at 0% friction)
2. Which pairs are robust to friction increases
3. The "friction tolerance" of each strategy-pair combo
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

# Pairs to test (all 31)
ALL_PAIRS = []
for f in sorted(DATA_DIR.glob('binance_*_USDT_240m.parquet')):
    pair = f.name.replace('binance_', '').replace('_USDT_240m.parquet', '')
    if pair not in ['BTC', 'ETH']:
        ALL_PAIRS.append(pair)

FRICTION_LEVELS = [0.0, 0.005, 0.01, 0.015, 0.02]


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
    bb_pct = (c - bb_lower) / (std20 * 4)
    
    ema8 = df['close'].ewm(span=8, adjust=False).mean().values
    ema21 = df['close'].ewm(span=21, adjust=False).mean().values
    ema55 = df['close'].ewm(span=55, adjust=False).mean().values
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    dc_upper = pd.Series(h).rolling(20).max().values
    dc_lower = pd.Series(l).rolling(20).min().values
    
    return c, o, h, l, rsi, bb_pct, ema8, ema21, ema55, atr, vol_ratio, dc_upper, dc_lower


def get_entries_mr(c, rsi, bb_pct, vol_ratio):
    entries = []
    for i in range(100, len(c)):
        if rsi[i] < 20 and bb_pct[i] < 0.1 and vol_ratio[i] > 1.5:
            entries.append(i)
    return entries


def get_entries_trend(ema8, ema21, ema55, c, adx, vol_ratio):
    # Simplified - just EMA alignment + pullback
    entries = []
    for i in range(100, len(c)):
        if (ema8[i] > ema21[i] > ema55[i] and
            c[i] <= ema21[i] * 1.01 and
            c[i] >= ema21[i] * 0.98 and
            vol_ratio[i] > 1.0):
            entries.append(i)
    return entries


def get_entries_breakout(c, dc_upper, vol_ratio):
    entries = []
    for i in range(100, len(c)):
        if c[i] > dc_upper[i-1] and vol_ratio[i] > 2.0:
            entries.append(i)
    return entries


def get_entries_momentum(c, rsi, ema8, ema21, vol_ratio):
    entries = []
    for i in range(100, len(c)):
        if (rsi[i] > 50 and rsi[i-1] <= 50 and
            ema8[i] > ema21[i] and
            vol_ratio[i] > 1.5):
            entries.append(i)
    return entries


def backtest_entries(entries, c, h, l, atr, stop_atr, target_atr, max_bars, friction):
    trades = []
    for idx in entries:
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


def calc_pf(t):
    if len(t) < 5:
        return 0
    w = t[t > 0]
    ls = t[t <= 0]
    if len(ls) == 0 or ls.sum() == 0:
        return 9.99 if len(w) > 0 else 0
    return w.sum() / abs(ls.sum())


print("=" * 120)
print("FRICTION ABLATION: Which Strategies Survive?")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

# Header
print(f"\n{'Pair':<10} {'Strat':<12}", end='')
for f in FRICTION_LEVELS:
    print(f"F={f*100:.1f}%{'':<5}", end='')
print("  Tolerance")
print("-" * 100)

results_summary = []

for pair in ALL_PAIRS:
    try:
        df = load_data(pair)
        if len(df) < 500:
            continue
        
        c, o, h, l, rsi, bb_pct, ema8, ema21, ema55, atr, vol_ratio, dc_upper, dc_lower = compute_indicators(df)
        
        strategies = [
            ('MR', lambda: get_entries_mr(c, rsi, bb_pct, vol_ratio), 0.75, 2.5, 15),
            ('TREND', lambda: get_entries_trend(ema8, ema21, ema55, c, None, vol_ratio), 1.0, 3.0, 20),
            ('MOMENTUM', lambda: get_entries_momentum(c, rsi, ema8, ema21, vol_ratio), 0.75, 2.0, 15),
            ('BREAKOUT', lambda: get_entries_breakout(c, dc_upper, vol_ratio), 1.0, 2.5, 15),
        ]
        
        for strat_name, entry_fn, stop_atr, target_atr, max_bars in strategies:
            entries = entry_fn()
            if len(entries) < 5:
                continue
            
            pfs = []
            for friction in FRICTION_LEVELS:
                trades = backtest_entries(entries, c, h, l, atr, stop_atr, target_atr, max_bars, friction)
                pf = calc_pf(trades)
                pfs.append(pf)
            
            # Calculate tolerance (max friction where PF >= 1.5)
            tolerance = 0
            for i, pf in enumerate(pfs):
                if pf >= 1.5:
                    tolerance = FRICTION_LEVELS[i]
            
            # Print if survives at 2%
            if pfs[-1] >= 1.5 or (tolerance > 0 and pfs[0] >= 3.0):
                print(f"{pair:<10} {strat_name:<12}", end='')
                for pf in pfs:
                    if pf >= 2.0:
                        print(f"\033[92m{pf:>5.2f}\033[0m{'':<8}", end='')
                    elif pf >= 1.0:
                        print(f"{pf:>5.2f}{'':<8}", end='')
                    else:
                        print(f"\033[91m{pf:>5.2f}\033[0m{'':<8}", end='')
                print(f"  {tolerance*100:.1f}%")
                
                results_summary.append({
                    'pair': pair, 'strategy': strat_name,
                    'pf_0': pfs[0], 'pf_2': pfs[-1], 'tolerance': tolerance
                })
    
    except Exception as e:
        print(f"{pair:<10} ERROR: {e}")

# Summary
print(f"\n{'=' * 120}")
print("PAIRS THAT SURVIVE 2% FRICTION (PF >= 1.5)")
print("=" * 120)

survivors = [r for r in results_summary if r['pf_2'] >= 1.5]
survivors.sort(key=lambda x: x['pf_2'], reverse=True)

print(f"\n{'Pair':<10} {'Strategy':<12} {'PF@0%':<10} {'PF@2%':<10} {'Tolerance'}")
print("-" * 60)
for r in survivors:
    print(f"{r['pair']:<10} {r['strategy']:<12} {r['pf_0']:<10.2f} {r['pf_2']:<10.2f} {r['tolerance']*100:.1f}%")

print(f"\nTotal survivors: {len(survivors)}")

# Raw edge analysis
print(f"\n{'=' * 120}")
print("RAW EDGE ANALYSIS (PF >= 3.0 at 0% friction)")
print("=" * 120)

raw_edge = [r for r in results_summary if r['pf_0'] >= 3.0]
raw_edge.sort(key=lambda x: x['pf_0'], reverse=True)

print(f"\n{'Pair':<10} {'Strategy':<12} {'PF@0%':<10} {'PF@2%':<10} {'Friction Tolerance'}")
print("-" * 70)
for r in raw_edge:
    print(f"{r['pair']:<10} {r['strategy']:<12} {r['pf_0']:<10.2f} {r['pf_2']:<10.2f} {r['tolerance']*100:.1f}%")
