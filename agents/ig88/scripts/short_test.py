"""
SHORT-Side Strategy: Proper Test
==================================
"""
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
FRICTION = 0.02

PAIRS = ['SUI', 'ARB', 'AAVE', 'AVAX', 'LINK', 'INJ', 'POL', 'SOL', 'NEAR', 'ATOM', 'UNI', 'OP']


def load_data(pair):
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    v = df['volume'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_upper = sma20 + std20 * 2
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    
    return c, o, h, l, rsi, bb_upper, atr, vol_ratio


def backtest_short(c, o, h, l, rsi, bb_upper, atr, vol_ratio, params, friction):
    """SHORT Mean Reversion: Price above BB + RSI overbought"""
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(rsi[i]) or np.isnan(bb_upper[i]) or np.isnan(atr[i]):
            continue
        
        # SHORT entry: Price above upper BB, RSI overbought
        if c[i] > bb_upper[i] and rsi[i] > params['rsi'] and vol_ratio[i] > params['vol']:
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price * (1 + atr[entry_bar] * params['stop'] / entry_price)  # Stop UP
            target_price = entry_price * (1 - atr[entry_bar] * params['target'] / entry_price)  # Target DOWN
            
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if h[bar] >= stop_price:  # Hit stop
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - friction)
                    break
                if l[bar] <= target_price:  # Hit target
                    trades.append(atr[entry_bar] * params['target'] / entry_price - friction)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                ret = (entry_price - exit_price) / entry_price - friction  # SHORT P&L
                trades.append(ret)
    
    return trades


def calc_stats(trades):
    if len(trades) < 3:
        return {'n': len(trades), 'pf': 0, 'exp': 0, 'wr': 0}
    t = np.array(trades)
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean()*100), 3), 'wr': round(float(len(w)/len(t)*100), 1)}


# Parameters
PARAM_GRID = {
    'rsi': [70, 75, 80],
    'vol': [1.2, 1.5, 2.0],
    'delay': [1, 2],
    'stop': [0.5, 0.75, 1.0],
    'target': [2.0, 2.5, 3.0],
}


print("=" * 100)
print("SHORT-SIDE STRATEGY TEST: Overbought Reversion")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 100)

print(f"\n{'Pair':<8} {'Train N':<10} {'Train Exp':<12} {'Test N':<10} {'Test Exp':<12} {'Verdict'}")
print("-" * 80)

viable_pairs = []

for pair in PAIRS:
    df = load_data(pair)
    n = len(df)
    train_end = int(n * 0.6)
    test_end = int(n * 0.8)
    
    c, o, h, l, rsi, bb_upper, atr, vol_ratio = compute_indicators(df)
    
    # Grid search on train
    keys = list(PARAM_GRID.keys())
    values = list(PARAM_GRID.values())
    all_combos = list(product(*values))
    
    np.random.seed(42)
    if len(all_combos) > 100:
        indices = np.random.choice(len(all_combos), 100, replace=False)
        combos = [all_combos[i] for i in indices]
    else:
        combos = all_combos
    
    best_exp = -999
    best_params = None
    
    for combo in combos:
        params = dict(zip(keys, combo))
        trades = backtest_short(
            c[:train_end], o[:train_end], h[:train_end], l[:train_end],
            rsi[:train_end], bb_upper[:train_end], atr[:train_end], vol_ratio[:train_end],
            params, FRICTION
        )
        stats = calc_stats(trades)
        if stats['n'] >= 5 and stats['exp'] > best_exp:
            best_exp = stats['exp']
            best_params = params
    
    if best_params is None:
        print(f"{pair:<8} NO VALID PARAMS")
        continue
    
    # Test on test period
    train_trades = backtest_short(
        c[:train_end], o[:train_end], h[:train_end], l[:train_end],
        rsi[:train_end], bb_upper[:train_end], atr[:train_end], vol_ratio[:train_end],
        best_params, FRICTION
    )
    
    test_trades = backtest_short(
        c[train_end:test_end], o[train_end:test_end], h[train_end:test_end], l[train_end:test_end],
        rsi[train_end:test_end], bb_upper[train_end:test_end], atr[train_end:test_end], vol_ratio[train_end:test_end],
        best_params, FRICTION
    )
    
    val_trades = backtest_short(
        c[test_end:], o[test_end:], h[test_end:], l[test_end:],
        rsi[test_end:], bb_upper[test_end:], atr[test_end:], vol_ratio[test_end:],
        best_params, FRICTION
    )
    
    train_stats = calc_stats(train_trades)
    test_stats = calc_stats(test_trades)
    val_stats = calc_stats(val_trades)
    
    profitable_count = sum([
        train_stats['exp'] > 0 and train_stats['n'] >= 3,
        test_stats['exp'] >= 0 and test_stats['n'] >= 1,
        val_stats['exp'] >= 0 and val_stats['n'] >= 1,
    ])
    
    is_valid = profitable_count >= 2 and (train_stats['n'] + test_stats['n'] + val_stats['n']) >= 10
    
    verdict = "VALID" if is_valid else "WEAK"
    
    if is_valid:
        viable_pairs.append(pair)
    
    print(f"{pair:<8} "
          f"{train_stats['n']:<4} {train_stats['exp']:>7.2f}%   "
          f"{test_stats['n']:<4} {test_stats['exp']:>7.2f}%   "
          f"{val_stats['n']:<4} {val_stats['exp']:>7.2f}%   "
          f"{verdict}")

print(f"\n{'=' * 100}")
print(f"VIABLE SHORT PAIRS: {len(viable_pairs)}/12")
print(f"Valid: {', '.join(viable_pairs) if viable_pairs else 'NONE'}")
