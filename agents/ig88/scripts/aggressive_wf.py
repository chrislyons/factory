"""
Walk-Forward Validation: Aggressive MR Parameters
====================================================
Validates optimized parameters on out-of-sample data.
Method: Train on first 60%, test on next 20%, validate on last 20%.
"""
import numpy as np
import pandas as pd
from pathlib import Path

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

# OPTIMIZED PARAMETERS
PORTFOLIO = {
    'INJ':  {'rsi': 20, 'bb': 2.0, 'vol': 2.5, 'stop': 0.75, 'target': 2.5, 'bars': 25},
    'ARB':  {'rsi': 20, 'bb': 2.0, 'vol': 2.0, 'stop': 0.5, 'target': 2.5, 'bars': 15},
    'SUI':  {'rsi': 20, 'bb': 3.0, 'vol': 1.5, 'stop': 0.75, 'target': 4.0, 'bars': 15},
    'AAVE': {'rsi': 20, 'bb': 3.0, 'vol': 2.5, 'stop': 1.0, 'target': 5.0, 'bars': 15},
    'AVAX': {'rsi': 20, 'bb': 2.5, 'vol': 2.5, 'stop': 0.5, 'target': 5.0, 'bars': 15},
    'LINK': {'rsi': 20, 'bb': 2.5, 'vol': 2.5, 'stop': 1.0, 'target': 2.0, 'bars': 20},
    'POL':  {'rsi': 20, 'bb': 2.0, 'vol': 1.5, 'stop': 0.75, 'target': 5.0, 'bars': 25},
}


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
    bb_lower_2 = sma20 - std20 * 2
    bb_lower_25 = sma20 - std20 * 2.5
    bb_lower_3 = sma20 - std20 * 3
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, o, h, l, rsi, bb_lower_2, bb_lower_25, bb_lower_3, atr, vol_ratio


def run_backtest(c, o, h, l, rsi, bb_low, atr, vol_ratio, params, friction):
    """Run backtest on given data segment."""
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
    
    return np.array(trades)


def calc_stats(t):
    if len(t) < 3:
        return {'n': len(t), 'pf': 0, 'exp': 0, 'wr': 0}
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {
        'n': len(t),
        'pf': round(float(pf), 3),
        'exp': round(float(t.mean() * 100), 3),
        'wr': round(float(len(w) / len(t) * 100), 1),
    }


print("=" * 100)
print("WALK-FORWARD VALIDATION: Aggressive MR Parameters")
print("=" * 100)

print(f"\n{'Pair':<8} {'Train N':<10} {'Train Exp':<12} {'Test N':<10} {'Test Exp':<12} {'Val N':<10} {'Val Exp':<12} {'Verdict'}")
print("-" * 100)

valid_count = 0
all_valid_trades = []

for pair, params in PORTFOLIO.items():
    df = load_data(pair)
    n = len(df)
    
    # Split: 60% train, 20% test, 20% validation
    train_end = int(n * 0.6)
    test_end = int(n * 0.8)
    
    c, o, h, l, rsi, bb2, bb25, bb3, atr, vol_ratio = compute_indicators(df)
    
    # Select BB
    if params['bb'] == 2.5:
        bb_low = bb25
    elif params['bb'] == 3.0:
        bb_low = bb3
    else:
        bb_low = bb2
    
    # Train (first 60%)
    train_trades = run_backtest(
        c[:train_end], o[:train_end], h[:train_end], l[:train_end],
        rsi[:train_end], bb_low[:train_end], atr[:train_end], vol_ratio[:train_end],
        params, FRICTION
    )
    
    # Test (next 20%)
    test_trades = run_backtest(
        c[train_end:test_end], o[train_end:test_end], 
        h[train_end:test_end], l[train_end:test_end],
        rsi[train_end:test_end], bb_low[train_end:test_end], 
        atr[train_end:test_end], vol_ratio[train_end:test_end],
        params, FRICTION
    )
    
    # Validation (last 20%)
    val_trades = run_backtest(
        c[test_end:], o[test_end:], h[test_end:], l[test_end:],
        rsi[test_end:], bb_low[test_end:], atr[test_end:], vol_ratio[test_end:],
        params, FRICTION
    )
    
    train_stats = calc_stats(train_trades)
    test_stats = calc_stats(test_trades)
    val_stats = calc_stats(val_trades)
    
    # Verdict: profitable in at least 2 of 3 periods
    profitable_periods = sum([
        train_stats['exp'] > 0 and train_stats['n'] >= 2,
        test_stats['exp'] > 0 and test_stats['n'] >= 1,
        val_stats['exp'] > 0 and val_stats['n'] >= 1,
    ])
    
    if profitable_periods >= 2:
        verdict = "VALID"
        valid_count += 1
        # Use validation trades for final tally
        if len(val_trades) > 0:
            all_valid_trades.extend(val_trades)
    else:
        verdict = "WEAK"
    
    print(f"{pair:<8} "
          f"{train_stats['n']:<4} {train_stats['exp']:>7.2f}%   "
          f"{test_stats['n']:<4} {test_stats['exp']:>7.2f}%   "
          f"{val_stats['n']:<4} {val_stats['exp']:>7.2f}%   "
          f"{verdict}")

# Summary
print(f"\n{'=' * 100}")
print(f"VALID PAIRS: {valid_count}/7")

if all_valid_trades:
    arr = np.array(all_valid_trades)
    w = arr[arr > 0]
    ls = arr[arr <= 0]
    
    print(f"\nValidation Period Totals (only VALID pairs):")
    print(f"  Trades: {len(arr)}")
    print(f"  Exp: {arr.mean()*100:.3f}%")
    print(f"  PF: {w.sum()/abs(ls.sum()):.2f}" if len(ls) > 0 else "  PF: inf")
    print(f"  WR: {(arr > 0).mean()*100:.1f}%")
