#!/usr/bin/env python3
"""
BTC/ETH Trend Optimization at Lower Friction
==============================================
Can we make trend work at 0.5% friction?
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

FRICTION_LEVELS = [0.005, 0.01, 0.015]


def load_data(pair):
    # Try 4h first (more data), then 1d
    for name in [f'binance_{pair}_USDT_240m.parquet', f'binance_{pair}_USD_1440m.parquet']:
        path = DATA_DIR / name
        if path.exists():
            return pd.read_parquet(path), '4h' if '240m' in name else '1d'
    return None, None


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    
    ema8 = pd.Series(c).ewm(span=8, adjust=False).mean().values
    ema21 = pd.Series(c).ewm(span=21, adjust=False).mean().values
    ema55 = pd.Series(c).ewm(span=55, adjust=False).mean().values
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    return c, h, l, ema8, ema21, ema55, atr, rsi


def backtest_trend(c, h, l, ema8, ema21, ema55, atr, friction, 
                   stop=2.0, target=4.0, max_bars=20, min_adx=0):
    entries = []
    
    for i in range(100, len(c) - max_bars):
        # EMA alignment
        if not (ema8[i] > ema21[i] > ema55[i]):
            continue
        
        # Pullback to EMA21 (within 2%)
        pullback = (c[i] - ema21[i]) / ema21[i]
        if not (-0.02 <= pullback <= 0.005):
            continue
        
        # Held above EMA21
        if c[i] > ema21[i] * 0.99:
            entries.append(i)
    
    trades = []
    for idx in entries:
        entry_bar = idx + 1
        entry_price = c[entry_bar]
        
        stop_price = entry_price - atr[entry_bar] * stop
        target_price = entry_price + atr[entry_bar] * target
        
        for j in range(1, max_bars + 1):
            bar = entry_bar + j
            if bar >= len(l):
                break
            if l[bar] <= stop_price:
                trades.append(-atr[entry_bar] * stop / entry_price - friction)
                break
            if h[bar] >= target_price:
                trades.append(atr[entry_bar] * target / entry_price - friction)
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
        return 9.99
    return w.sum() / abs(ls.sum())


print("=" * 100)
print("BTC/ETH TREND OPTIMIZATION: FRICTION SENSITIVITY")
print("=" * 100)

for pair in ['BTC', 'ETH']:
    df, tf = load_data(pair)
    if df is None:
        continue
    
    print(f"\n{'=' * 60}")
    print(f"{pair} ({tf} timeframe, {len(df)} bars)")
    print(f"{'=' * 60}")
    
    c, h, l, ema8, ema21, ema55, atr, rsi = compute_indicators(df)
    
    print(f"\n{'Config':<25}", end='')
    for f in FRICTION_LEVELS:
        print(f"F={f*100:.1f}%{'':<6}", end='')
    print("  Best")
    print("-" * 80)
    
    best_configs = []
    
    for stop in [1.5, 2.0, 2.5, 3.0]:
        for target in [3.0, 4.0, 5.0, 6.0]:
            for bars in [15, 20, 25]:
                config_name = f"S{stop} T{target} B{bars}"
                
                print(f"{config_name:<25}", end='')
                
                best_friction = None
                best_pf = 0
                
                for friction in FRICTION_LEVELS:
                    trades = backtest_trend(c, h, l, ema8, ema21, ema55, atr, friction,
                                           stop, target, bars)
                    
                    if len(trades) >= 10:
                        pf = calc_pf(trades)
                        
                        if pf >= 1.5:
                            print(f"\033[92m{pf:>5.2f}/{len(trades)}\033[0m{'':<2}", end='')
                            if pf > best_pf:
                                best_pf = pf
                                best_friction = friction
                        else:
                            print(f"{pf:>5.2f}/{len(trades)}{'':<2}", end='')
                        
                        if pf > best_pf:
                            best_pf = pf
                            best_friction = friction
                    else:
                        print(f"n<10{'':<4}", end='')
                
                if best_pf >= 1.5:
                    best_configs.append((pair, config_name, best_pf, best_friction, stop, target, bars))
                    print(f"  VIABLE @ {best_friction*100:.1f}%")
                else:
                    print()

print(f"\n{'=' * 100}")
print("VIABLE BTC/ETH TREND CONFIGS")
print("=" * 100)

if best_configs:
    for pair, config, pf, friction, stop, target, bars in best_configs:
        print(f"{pair}: {config} | PF={pf:.2f} @ {friction*100:.1f}% friction")
else:
    print("""
No viable configs found. BTC/ETH trend strategies need:
1. Friction < 0.5% (achievable with Kraken tier 2)
2. OR different timeframe
3. OR different strategy class (funding rate arb, etc.)

CONCLUSION: Focus on the 15-pair MR portfolio for now.
BTC/ETH are not tradeable with our current approach.
""")
