"""
Expand Universe: Test More Altcoins for Aggressive MR
======================================================
Tests additional pairs beyond original 12 to find more viable setups.
"""
import numpy as np
import pandas as pd
from pathlib import Path
import json
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# Extended universe - check what data we have
EXTRA_PAIRS = ['APT', 'FIL', 'DOT', 'FTM', 'RUNE', 'IMX', 'MKR', 'LDO', 
               'COMP', 'DYDX', 'SNX', 'CRV', 'GRT', '1INCH', 'SAND', 'MANA']


def check_data(pair):
    """Check if we have data for this pair."""
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if path.exists():
        df = pd.read_parquet(path)
        return len(df)
    return 0


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
    bb_lower_2 = sma20 - std20 * 2
    bb_lower_25 = sma20 - std20 * 2.5
    bb_lower_3 = sma20 - std20 * 3
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, o, h, l, rsi, bb_lower_2, bb_lower_25, bb_lower_3, atr, vol_ratio


def test_pair(pair, params, friction):
    """Test a pair with aggressive MR parameters."""
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if not path.exists():
        return None
    
    df = pd.read_parquet(path)
    if len(df) < 200:
        return None
    
    c, o, h, l, rsi, bb2, bb25, bb3, atr, vol_ratio = compute_indicators(df)
    
    # Select BB
    if params['bb'] == 2.5:
        bb_low = bb25
    elif params['bb'] == 3.0:
        bb_low = bb3
    else:
        bb_low = bb2
    
    trades = []
    for i in range(100, len(c) - params['bars']):
        if np.isnan(rsi[i]) or np.isnan(bb_low[i]) or np.isnan(atr[i]):
            continue
        
        if rsi[i] < params['rsi'] and c[i] < bb_low[i] and vol_ratio[i] > params['vol']:
            entry_bar = i + 2
            if entry_bar >= len(c) - params['bars']:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop']
            target_price = entry_price + atr[entry_bar] * params['target']
            
            for j in range(1, params['bars']):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - friction)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target'] / entry_price - friction)
                    break
            else:
                exit_price = c[min(entry_bar + params['bars'], len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - friction)
    
    trades = np.array(trades)
    if len(trades) < 5:
        return {'n': len(trades), 'exp': 0, 'pf': 0, 'wr': 0}
    
    w = trades[trades > 0]
    ls = trades[trades <= 0]
    
    return {
        'n': len(trades),
        'exp': round(float(trades.mean() * 100), 3),
        'pf': round(float(w.sum() / abs(ls.sum())) if len(ls) > 0 and ls.sum() != 0 else 999, 2),
        'wr': round(float(len(w) / len(trades) * 100), 1),
    }


# Test parameters
PARAMS = [
    {'rsi': 20, 'bb': 2.0, 'vol': 1.5, 'stop': 0.75, 'target': 2.5, 'bars': 15},
    {'rsi': 20, 'bb': 2.0, 'vol': 2.0, 'stop': 0.5, 'target': 3.0, 'bars': 15},
    {'rsi': 25, 'bb': 2.5, 'vol': 1.5, 'stop': 1.0, 'target': 2.5, 'bars': 20},
]

print("=" * 100)
print("EXPAND UNIVERSE: Testing additional altcoins for aggressive MR")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 100)

# Original pairs
ORIG_PAIRS = ['SUI', 'ARB', 'AAVE', 'AVAX', 'LINK', 'INJ', 'POL', 'SOL', 'NEAR', 'ATOM', 'UNI', 'OP']

print("\nORIGINAL PAIRS:")
print(f"{'Pair':<8} {'Data':<10} {'N':<6} {'Exp%':<10} {'PF':<8} {'WR%':<8} {'Verdict'}")
print("-" * 70)

for pair in ORIG_PAIRS:
    n_bars = check_data(pair)
    if n_bars == 0:
        print(f"{pair:<8} NO DATA")
        continue
    
    # Test with best param set
    result = test_pair(pair, PARAMS[0], FRICTION)
    if result and result['n'] >= 5:
        verdict = "PROD" if result['exp'] > 1.0 else "MARGINAL" if result['exp'] > 0 else "NEGATIVE"
        print(f"{pair:<8} {n_bars:<10} {result['n']:<6} {result['exp']:>7.2f}%  {result['pf']:<8.2f} {result['wr']:<8.1f} {verdict}")
    else:
        print(f"{pair:<8} {n_bars:<10} {result['n'] if result else 0:<6} {'TOO FEW':>7}")

print("\nNEW PAIRS:")
print(f"{'Pair':<8} {'Data':<10} {'N':<6} {'Exp%':<10} {'PF':<8} {'WR%':<8} {'Verdict'}")
print("-" * 70)

viable_new = []
for pair in EXTRA_PAIRS:
    n_bars = check_data(pair)
    if n_bars == 0:
        print(f"{pair:<8} NO DATA")
        continue
    
    # Test all param sets, pick best
    best = None
    for params in PARAMS:
        result = test_pair(pair, params, FRICTION)
        if result and result['n'] >= 5 and result['exp'] > 0:
            if best is None or result['exp'] > best['exp']:
                best = result
    
    if best and best['n'] >= 5:
        verdict = "VIABLE" if best['exp'] > 1.0 else "MARGINAL"
        print(f"{pair:<8} {n_bars:<10} {best['n']:<6} {best['exp']:>7.2f}%  {best['pf']:<8.2f} {best['wr']:<8.1f} {verdict}")
        if best['exp'] > 0.5:
            viable_new.append((pair, best))
    else:
        print(f"{pair:<8} {n_bars:<10} {'N/A':<6}")

print(f"\n{'=' * 100}")
print(f"VIABLE NEW PAIRS: {len(viable_new)}")
for pair, stats in viable_new:
    print(f"  {pair}: Exp={stats['exp']:.2f}%, PF={stats['pf']}, N={stats['n']}")
