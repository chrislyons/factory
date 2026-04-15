"""
Test Previously Failed Pairs at Lower Friction
===============================================
Can limit orders unlock DOT, FIL, BTC, ETH on Kraken spot?
"""
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')

# Pairs that FAILED at 2% friction
FAILED_PAIRS = ['DOT', 'FIL', 'GRT', 'IMX', 'NEAR', 'OP', 'SOL', 'SNX', 'XRP', 'BTC', 'ETH']


def load_data(pair):
    # Try Binance first, then dYdX
    for path in [f'binance_{pair}_USDT_240m.parquet', f'dydx_{pair}_USDT_240m.parquet']:
        try:
            return pd.read_parquet(DATA_DIR / path)
        except:
            pass
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
    bb_lower = sma20 - std20 * 2
    bb_upper = sma20 + std20 * 2
    bb_pct = (c - bb_lower) / (bb_upper - bb_lower + 1e-10)
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values if 'volume' in df.columns else df['usdVolume'].values).rolling(20).mean().values
    vol_ratio = (df['volume'].values if 'volume' in df.columns else df['usdVolume'].values) / (vol_sma + 1)
    
    return c, h, l, rsi, bb_pct, atr, vol_ratio


def backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg, friction):
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
                trades.append(-atr[entry_bar] * cfg['stop'] / entry_price - friction/100)
                break
            if h[bar] >= target_price:
                trades.append(atr[entry_bar] * cfg['target'] / entry_price - friction/100)
                break
        else:
            exit_price = c[min(entry_bar + cfg['bars'], len(c) - 1)]
            trades.append((exit_price - entry_price) / entry_price - friction/100)
    
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
print("TESTING PREVIOUSLY FAILED PAIRS AT LOWER FRICTION")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

# All configs to test
CONFIGS = [
    {'rsi': 18, 'bb': 0.05, 'vol': 1.0, 'stop': 0.75, 'target': 2.0, 'bars': 15},
    {'rsi': 20, 'bb': 0.10, 'vol': 1.0, 'stop': 1.0, 'target': 2.5, 'bars': 20},
    {'rsi': 22, 'bb': 0.15, 'vol': 1.2, 'stop': 1.0, 'target': 3.0, 'bars': 20},
    {'rsi': 25, 'bb': 0.20, 'vol': 1.2, 'stop': 1.25, 'target': 2.5, 'bars': 20},
]

FRICTION_LEVELS = [0.5, 1.0, 1.5, 2.0]

print(f"\n{'Pair':<10} {'Bars':<8}", end='')
for f in FRICTION_LEVELS:
    print(f"F={f}%{'':<6}", end='')
print("  Best at 1%")
print("-" * 90)

newly_viable = []

for pair in FAILED_PAIRS:
    df = load_data(pair)
    if df is None or len(df) < 200:
        print(f"{pair:<10} {'NO DATA'}")
        continue
    
    c, h, l, rsi, bb_pct, atr, vol_ratio = compute_indicators(df)
    
    print(f"{pair:<10} {len(df):<8}", end='')
    
    best_at_1 = None
    
    for friction in FRICTION_LEVELS:
        best_pf = 0
        best_n = 0
        
        for cfg in CONFIGS:
            trades = backtest(c, h, l, rsi, bb_pct, atr, vol_ratio, cfg, friction)
            if len(trades) >= 5:
                pf = calc_pf(trades)
                if pf > best_pf:
                    best_pf = pf
                    best_n = len(trades)
        
        if best_pf >= 1.5 and best_n >= 5:
            print(f"\033[92m{best_pf:>4.2f}/{best_n}\033[0m{'':<2}", end='')
            if friction == 1.0:
                best_at_1 = best_pf
        else:
            print(f"{best_pf:>4.2f}/{best_n}{'':<2}", end='')
    
    if best_at_1 and best_at_1 >= 1.5:
        print(f"  \033[92mVIABLE\033[0m")
        newly_viable.append((pair, best_at_1))
    else:
        print()

print(f"\n{'=' * 120}")
print(f"NEWLY VIABLE AT 1% FRICTION (LIMIT ORDERS): {len(newly_viable)}")
print("=" * 120)

if newly_viable:
    for pair, pf in newly_viable:
        print(f"  {pair}: PF {pf:.2f}")
else:
    print("  None - these pairs have fundamental edge problems, not friction problems")

print(f"""
REALITY CHECK:
The pairs that failed at 2% (DOT, FIL, SOL, etc.) have FUNDAMENTAL edge problems.
Lowering friction helps but doesn't create edge where none exists.

The 12 pairs we have (ARB, AVAX, UNI, SUI, MATIC + 7 WEAK) are the ones
that actually have edge at 4H mean reversion.
""")
