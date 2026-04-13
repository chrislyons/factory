"""
Walk-Forward Strategy Optimizer
================================
Validates strategies with proper walk-forward methodology:
1. Optimize on first 60% of data
2. Test on next 20% (out-of-sample)
3. Only report strategies that are profitable in BOTH periods

This eliminates overfitting that the grid search was showing.
"""
import numpy as np
import pandas as pd
from pathlib import Path
from itertools import product
import json
from datetime import datetime

DATA_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data')
RESULTS_DIR = Path('/Users/nesbitt/dev/factory/agents/ig88/data/optimization')
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PAIRS = ['SOL', 'NEAR', 'LINK', 'AVAX', 'ATOM', 'UNI', 'AAVE', 'ARB', 'OP', 'INJ', 'SUI', 'POL']

# Conservative friction levels (projecting for real-world costs)
FRICTION_LEVELS = [0.015, 0.02]  # 1.5%, 2.0%


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
    v = df['volume'].values
    
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    
    ema_12 = df['close'].ewm(span=12, adjust=False).mean().values
    ema_26 = df['close'].ewm(span=26, adjust=False).mean().values
    
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    
    donchian_upper = pd.Series(h).rolling(20).max().values
    
    return {
        'close': c, 'open': o, 'high': h, 'low': l, 'volume': v,
        'rsi': rsi, 'bb_lower': bb_lower, 'ema_12': ema_12, 'ema_26': ema_26,
        'atr': atr, 'vol_ratio': vol_ratio, 'donchian_upper': donchian_upper,
    }


def run_mr_backtest(ind, params, friction):
    """MR: RSI oversold + BB lower + Volume surge"""
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    rsi, bb_lower, atr, vol_ratio = ind['rsi'], ind['bb_lower'], ind['atr'], ind['vol_ratio']
    
    trades = []
    for i in range(100, len(c) - 20):
        if np.isnan(rsi[i]) or np.isnan(bb_lower[i]) or np.isnan(atr[i]):
            continue
        if rsi[i] < params['rsi'] and c[i] < bb_lower[i] and vol_ratio[i] > params['vol']:
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


def run_bo_backtest(ind, params, friction):
    """BO: Donchian breakout + Volume surge"""
    c, o, h, l = ind['close'], ind['open'], ind['high'], ind['low']
    atr, vol_ratio, donchian = ind['atr'], ind['vol_ratio'], ind['donchian_upper']
    
    trades = []
    for i in range(100, len(c) - 20):
        if np.isnan(donchian[i]) or np.isnan(atr[i]):
            continue
        if c[i] > donchian[i-1] and vol_ratio[i] > params['vol']:
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


def wf_optimize(pair, strategy_type, friction):
    """
    Walk-forward optimization:
    - Train: First 60% of data
    - Test: Next 20% of data
    - Validation: Last 20% (held out entirely)
    """
    df = load_data(pair)
    if df is None:
        return None
    
    n = len(df)
    train_end = int(n * 0.6)
    test_end = int(n * 0.8)
    
    train_df = df.iloc[:train_end]
    test_df = df.iloc[train_end:test_end]
    
    train_ind = compute_indicators(train_df)
    test_ind = compute_indicators(test_df)
    
    # Parameter grid
    if strategy_type == 'MR':
        param_grid = {
            'rsi': [20, 25, 30],
            'vol': [1.3, 1.5, 1.8],
            'delay': [2, 3],
            'stop_atr': [0.75, 1.0, 1.5],
            'target_atr': [1.5, 2.0, 2.5, 3.0],
        }
        run_func = run_mr_backtest
    else:  # BREAKOUT
        param_grid = {
            'vol': [1.3, 1.5, 1.8],
            'delay': [1, 2],
            'stop_atr': [0.75, 1.0, 1.5],
            'target_atr': [2.0, 2.5, 3.0],
        }
        run_func = run_bo_backtest
    
    # Grid search on TRAIN data
    keys = list(param_grid.keys())
    values = list(param_grid.values())
    all_combos = list(product(*values))
    
    best_train_exp = -999
    best_params = None
    
    for combo in all_combos:
        params = dict(zip(keys, combo))
        trades = run_func(train_ind, params, friction)
        stats = calc_stats(trades)
        
        if stats['n'] >= 10 and stats['exp'] > best_train_exp:
            best_train_exp = stats['exp']
            best_params = params
    
    if best_params is None:
        return None
    
    # Test on OOS data
    train_trades = run_func(train_ind, best_params, friction)
    test_trades = run_func(test_ind, best_params, friction)
    
    train_stats = calc_stats(train_trades)
    test_stats = calc_stats(test_trades)
    
    # Valid = profitable in BOTH periods
    is_valid = train_stats['exp'] > 0 and test_stats['exp'] > 0 and train_stats['n'] >= 5 and test_stats['n'] >= 3
    
    return {
        'pair': pair,
        'strategy': strategy_type,
        'friction': friction,
        'params': best_params,
        'train': train_stats,
        'test': test_stats,
        'valid': is_valid,
    }


print("=" * 100)
print("WALK-FORWARD OPTIMIZER (proper validation)")
print(f"Designing for 1.5-2.0% friction")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 100)

all_results = []

for friction in FRICTION_LEVELS:
    print(f"\n{'=' * 100}")
    print(f"FRICTION: {friction*100:.0f}%")
    print(f"{'=' * 100}")
    
    valid_pairs = []
    
    for pair in PAIRS:
        # Test both MR and Breakout
        mr_result = wf_optimize(pair, 'MR', friction)
        bo_result = wf_optimize(pair, 'BO', friction)
        
        # Pick the one with better OOS performance
        best = None
        if mr_result and mr_result['valid']:
            best = mr_result
        if bo_result and bo_result['valid']:
            if best is None or bo_result['test']['exp'] > best['test']['exp']:
                best = bo_result
        
        if best:
            all_results.append(best)
            valid_pairs.append(pair)
            print(f"{pair:<8} {best['strategy']:<6} Train: {best['train']['exp']:+.2f}% ({best['train']['n']}t) | OOS: {best['test']['exp']:+.2f}% ({best['test']['n']}t) | VALID")
        else:
            # Show why each failed
            mr_info = f"MR Train={mr_result['train']['exp']:.2f}% OOS={mr_result['test']['exp']:.2f}%" if mr_result else "MR: no signals"
            bo_info = f"BO Train={bo_result['train']['exp']:.2f}% OOS={bo_result['test']['exp']:.2f}%" if bo_result else "BO: no signals"
            print(f"{pair:<8} FAILED | {mr_info} | {bo_info}")
    
    print(f"\nValid pairs at {friction*100:.0f}% friction: {len(valid_pairs)}/12")
    print(f"Pairs: {', '.join(valid_pairs) if valid_pairs else 'NONE'}")

# Save results
results_path = RESULTS_DIR / f"wf_optimization_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
with open(results_path, 'w') as f:
    json.dump(all_results, f, indent=2, default=str)

print(f"\nResults saved to: {results_path}")
