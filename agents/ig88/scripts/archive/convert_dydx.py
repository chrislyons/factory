#!/usr/bin/env python3
"""Convert dYdX JSON to parquet and test at 0.5% friction."""
import json
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.005  # 0.5% - perps with maker rebates

TARGETS = ['BTC', 'ETH', 'SOL', 'AVAX', 'ARB', 'LINK', 'UNI', 'MATIC', 
           'ATOM', 'AAVE', 'SUI', 'INJ', 'ADA', 'ALGO', 'LTC', 'NEAR', 'DOT', 'FIL']


def load_dydx_json(pair):
    json_file = DATA_DIR / f'dydx_{pair}-USD.json'
    if not json_file.exists():
        return None
    
    with open(json_file) as f:
        data = json.load(f)
    
    if 'candles' not in data or not data['candles']:
        return None
    
    df = pd.DataFrame(data['candles'])
    
    for col in ['open', 'high', 'low', 'close', 'usdVolume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df['timestamp'] = pd.to_datetime(df['startedAt'])
    df = df.set_index('timestamp').sort_index()
    
    return df


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
    
    vol_sma = pd.Series(df['usdVolume'].values).rolling(20).mean().values
    vol_ratio = df['usdVolume'].values / (vol_sma + 1)
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio


def backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg):
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
                trades.append(-atr[entry_bar] * cfg['stop'] / entry_price - FRICTION)
                break
            if h[bar] >= target_price:
                trades.append(atr[entry_bar] * cfg['target'] / entry_price - FRICTION)
                break
        else:
            exit_price = c[min(entry_bar + cfg['bars'], len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return np.array(trades)


def calc_pf(t):
    if len(t) < 5:
        return 0
    w = t[t > 0]
    ls = t[t <= 0]
    if len(ls) == 0 or ls.sum() == 0:
        return 9.99
    return w.sum() / abs(ls.sum())


print("=" * 120)
print("dYdX PERPS: TEST AT 0.5% FRICTION (MAKER REBATES)")
print("=" * 120)

results = []

print(f"\n{'Pair':<10} {'Candles':<10} {'ATR%':<10} {'Best N':<10} {'Best PF':<10} {'Best Exp%':<12} {'R:R'}")
print("-" * 80)

for pair in TARGETS:
    df = load_dydx_json(pair)
    if df is None or len(df) < 200:
        print(f"{pair:<10} {'NO DATA'}")
        continue
    
    c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)
    
    atr_pct = atr[100:] / c[100:] * 100
    
    best = None
    
    for rsi_t in [18, 22, 25]:
        for bb_t in [0.05, 0.1, 0.15, 0.2]:
            for vol_t in [1.0, 1.2, 1.5]:
                for stop in [0.75, 1.0, 1.25]:
                    for target in [1.5, 2.0, 2.5, 3.0]:
                        for bars in [15, 20]:
                            cfg = {'rsi': rsi_t, 'bb': bb_t, 'vol': vol_t, 
                                   'stop': stop, 'target': target, 'bars': bars}
                            trades = backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg)
                            
                            if len(trades) < 8:
                                continue
                            
                            pf = calc_pf(trades)
                            
                            if pf >= 1.5:
                                exp = trades.mean() * 100
                                rr = target / stop
                                
                                if best is None or pf > best['pf']:
                                    best = {'n': len(trades), 'pf': pf, 'exp': exp, 
                                            'rr': rr, 'cfg': cfg}
    
    if best:
        results.append({'pair': pair, **best})
        print(f"{pair:<10} {len(df):<10} {atr_pct.mean():<10.2f} {best['n']:<10} {best['pf']:<10.2f} {best['exp']:<12.2f} 1:{best['rr']:.0f}")
    else:
        print(f"{pair:<10} {len(df):<10} {atr_pct.mean():<10.2f} {'NO EDGE'}")

# Summary
print(f"\n{'=' * 120}")
print(f"VIABLE PAIRS AT 0.5% FRICTION: {len(results)}")
print("=" * 120)

if results:
    results.sort(key=lambda x: x['pf'], reverse=True)
    
    print(f"\n{'Pair':<10} {'N':<8} {'PF':<10} {'Exp%':<10} {'R:R':<10} {'Size'}")
    print("-" * 60)
    
    for r in results:
        size = 2.5 if r['pf'] >= 3.0 else 2.0 if r['pf'] >= 2.0 else 1.0
        print(f"{r['pair']:<10} {r['n']:<8} {r['pf']:<10.2f} {r['exp']:<10.2f} 1:{r['rr']:<7.0f} {size}%")
    
    total_trades = sum(r['n'] for r in results)
    avg_pf = np.mean([r['pf'] for r in results])
    avg_exp = np.mean([r['exp'] for r in results])
    
    print(f"\nPortfolio Summary:")
    print(f"  Viable pairs: {len(results)}")
    print(f"  Total expected trades: {total_trades}")
    print(f"  Average PF: {avg_pf:.2f}")
    print(f"  Average expectancy: {avg_exp:.2f}%")
