"""
Walk-Forward Validation: Keltner Channel Reversion
====================================================
Validates Keltner Rev across all 12 pairs with proper WF methodology.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product
import json
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

PAIRS = ['SUI', 'ARB', 'AAVE', 'AVAX', 'LINK', 'INJ', 'POL', 'SOL', 'NEAR', 'ATOM', 'UNI', 'OP']


def load_data(pair):
    path = DATA_DIR / f'binance_{pair}_USDT_240m.parquet'
    if not path.exists():
        return None
    return pd.read_parquet(path)


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # Keltner Channels
    kelt_mid = df['close'].ewm(span=20, adjust=False).mean().values
    kelt_upper = kelt_mid + atr * 2
    kelt_lower = kelt_mid - atr * 2
    
    vol_sma = pd.Series(df['volume'].values).rolling(20).mean().values
    vol_ratio = df['volume'].values / vol_sma
    
    return c, o, h, l, rsi, kelt_lower, kelt_mid, atr, vol_ratio


def run_keltner_backtest(c, o, h, l, rsi, kelt_lower, kelt_mid, atr, vol_ratio, params, friction):
    """Run Keltner Reversion backtest."""
    trades = []
    for i in range(100, len(c) - 20):
        if np.isnan(kelt_lower[i]) or np.isnan(rsi[i]) or np.isnan(atr[i]):
            continue
        
        if (c[i] < kelt_lower[i] and 
            rsi[i] < params['rsi'] and 
            vol_ratio[i] > params['vol']):
            
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop_atr']
            target_price = entry_price + atr[entry_bar] * params['target_atr']
            
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop_atr'] / entry_price - friction)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target_atr'] / entry_price - friction)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - friction)
    
    return np.array(trades)


def calc_stats(t):
    if len(t) < 5:
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


# Parameter grid
PARAM_GRID = {
    'rsi': [20, 25, 30],
    'vol': [1.3, 1.5, 1.8],
    'delay': [1, 2],
    'stop_atr': [0.5, 0.75, 1.0],
    'target_atr': [2.0, 2.5, 3.0],
}


print("=" * 120)
print("WALK-FORWARD VALIDATION: Keltner Channel Reversion")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

print(f"\n{'Pair':<8} {'Train N':<10} {'Train Exp':<12} {'Test N':<10} {'Test Exp':<12} {'Val N':<10} {'Val Exp':<12} {'Verdict'}")
print("-" * 110)

valid_pairs = []
all_val_trades = []

for pair in PAIRS:
    df = load_data(pair)
    if df is None:
        print(f"{pair:<8} NO DATA")
        continue
    
    n = len(df)
    train_end = int(n * 0.6)
    test_end = int(n * 0.8)
    
    c, o, h, l, rsi, kelt_lower, kelt_mid, atr, vol_ratio = compute_indicators(df)
    
    # Grid search on TRAIN
    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    all_combos = list(product(*values))
    
    np.random.seed(42)
    if len(all_combos) > 100:
        indices = np.random.choice(len(all_combos), 100, replace=False)
        combos = [all_combos[i] for i in indices]
    else:
        combos = all_combos
    
    best_params = None
    best_train_exp = -999
    
    for combo in combos:
        params = dict(zip(keys, combo))
        trades = run_keltner_backtest(
            c[:train_end], o[:train_end], h[:train_end], l[:train_end],
            rsi[:train_end], kelt_lower[:train_end], kelt_mid[:train_end],
            atr[:train_end], vol_ratio[:train_end],
            params, FRICTION
        )
        stats = calc_stats(trades)
        if stats['n'] >= 5 and stats['exp'] > best_train_exp:
            best_train_exp = stats['exp']
            best_params = params
    
    if best_params is None:
        print(f"{pair:<8} NO VALID PARAMS")
        continue
    
    # Test on all three periods
    train_trades = run_keltner_backtest(
        c[:train_end], o[:train_end], h[:train_end], l[:train_end],
        rsi[:train_end], kelt_lower[:train_end], kelt_mid[:train_end],
        atr[:train_end], vol_ratio[:train_end],
        best_params, FRICTION
    )
    
    test_trades = run_keltner_backtest(
        c[train_end:test_end], o[train_end:test_end], 
        h[train_end:test_end], l[train_end:test_end],
        rsi[train_end:test_end], kelt_lower[train_end:test_end], 
        kelt_mid[train_end:test_end], atr[train_end:test_end], 
        vol_ratio[train_end:test_end],
        best_params, FRICTION
    )
    
    val_trades = run_keltner_backtest(
        c[test_end:], o[test_end:], h[test_end:], l[test_end:],
        rsi[test_end:], kelt_lower[test_end:], kelt_mid[test_end:],
        atr[test_end:], vol_ratio[test_end:],
        best_params, FRICTION
    )
    
    train_stats = calc_stats(train_trades)
    test_stats = calc_stats(test_trades)
    val_stats = calc_stats(val_trades)
    
    # Valid = profitable in at least 2 of 3 periods with sufficient trades
    profitable_count = sum([
        train_stats['exp'] > 0 and train_stats['n'] >= 3,
        test_stats['exp'] > 0 and test_stats['n'] >= 2,
        val_stats['exp'] > 0 and val_stats['n'] >= 2,
    ])
    
    is_valid = profitable_count >= 2 and val_stats['n'] >= 2
    
    if is_valid:
        verdict = "VALID"
        valid_pairs.append(pair)
        if len(val_trades) > 0:
            all_val_trades.extend(val_trades)
    else:
        verdict = "WEAK"
    
    print(f"{pair:<8} "
          f"{train_stats['n']:<4} {train_stats['exp']:>7.2f}%   "
          f"{test_stats['n']:<4} {test_stats['exp']:>7.2f}%   "
          f"{val_stats['n']:<4} {val_stats['exp']:>7.2f}%   "
          f"{verdict}")

print(f"\n{'=' * 120}")
print(f"VALID PAIRS: {len(valid_pairs)}/12")
print(f"Valid: {', '.join(valid_pairs)}")

if all_val_trades:
    arr = np.array(all_val_trades)
    w = arr[arr > 0]
    ls = arr[arr <= 0]
    
    print(f"\nValidation Period Totals (valid pairs only):")
    print(f"  Trades: {len(arr)}")
    print(f"  Expectancy: {arr.mean()*100:.3f}%")
    print(f"  Profit Factor: {w.sum()/abs(ls.sum()):.2f}" if len(ls) > 0 else "  PF: inf")
    print(f"  Win Rate: {(arr > 0).mean()*100:.1f}%")
    
    # Monte Carlo
    np.random.seed(42)
    n_sim = 10000
    returns = []
    for _ in range(n_sim):
        sampled = np.random.choice(arr, size=30, replace=True)  # ~2.5/month x 12
        returns.append(sampled.sum())
    returns = np.array(returns)
    
    print(f"\nMonte Carlo (12 months, ~2.5 trades/month):")
    print(f"  Mean: {returns.mean()*100:.1f}%")
    print(f"  Median: {np.median(returns)*100:.1f}%")
    print(f"  5th pctl: {np.percentile(returns, 5)*100:.1f}%")
    print(f"  Prob > 0: {(returns > 0).mean()*100:.1f}%")
    print(f"  Prob > 50%: {(returns > 0.5).mean()*100:.1f}%")
    print(f"  Prob loss >20%: {(returns < -0.2).mean()*100:.1f}%")
