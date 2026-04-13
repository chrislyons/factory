"""
ADX-Based Strategy
==================
Uses trend strength (ADX) as primary filter - NOT RSI.
Different market regime detection than MR.
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
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # ADX components
    plus_dm = np.maximum(np.diff(h, prepend=h[0]), 0)
    minus_dm = np.maximum(-np.diff(l, prepend=l[0]), 0)
    
    atr_smooth = pd.Series(tr).rolling(14).mean().values
    plus_di = 100 * pd.Series(plus_dm).rolling(14).mean() / (atr_smooth + 1e-10)
    minus_di = 100 * pd.Series(minus_dm).rolling(14).mean() / (atr_smooth + 1e-10)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-10)
    adx = pd.Series(dx).rolling(14).mean().values
    
    # EMAs for trend direction
    ema_8 = df['close'].ewm(span=8, adjust=False).mean().values
    ema_21 = df['close'].ewm(span=21, adjust=False).mean().values
    
    # Vol
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    
    return {
        'c': c, 'o': o, 'h': h, 'l': l,
        'atr': atr,
        'adx': adx, 'plus_di': plus_di.values, 'minus_di': minus_di.values,
        'ema_8': ema_8, 'ema_21': ema_21,
        'vol_ratio': vol_ratio,
    }


def strat_adx_bounce(ind, params):
    """
    ADX BOUNCE: Low ADX (choppy) + Price at support -> mean reversion
    When ADX is low, mean reversion works better.
    """
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    atr = ind['atr']
    adx = ind['adx']
    ema_21 = ind['ema_21']
    vol_ratio = ind['vol_ratio']
    
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(adx[i]) or np.isnan(ema_21[i]) or np.isnan(atr[i]):
            continue
        
        # Low ADX (ranging) + Price below EMA21 + Volume confirmation
        if (adx[i] < params['adx_max'] and
            c[i] < ema_21[i] * (1 - params['ema_dist'] / 100) and
            vol_ratio[i] > params['vol']):
            
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop']
            target_price = entry_price + atr[entry_bar] * params['target']
            
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return trades


def strat_di_crossover(ind, params):
    """
    DI CROSSOVER: Plus-DI crosses above Minus-DI with ADX confirmation
    Trend-following entry with strength filter.
    """
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    atr = ind['atr']
    adx = ind['adx']
    plus_di = ind['plus_di']
    minus_di = ind['minus_di']
    vol_ratio = ind['vol_ratio']
    
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(adx[i]) or np.isnan(plus_di[i]) or np.isnan(minus_di[i]):
            continue
        
        # Plus-DI just crossed above Minus-DI, ADX rising
        if (plus_di[i] > minus_di[i] and
            plus_di[i-1] <= minus_di[i-1] and  # Crossover
            adx[i] > params['adx_min'] and  # Strong enough trend
            vol_ratio[i] > params['vol']):
            
            entry_bar = i + params['delay']
            if entry_bar >= len(c) - 15:
                continue
            
            entry_price = o[entry_bar]
            stop_price = entry_price - atr[entry_bar] * params['stop']
            target_price = entry_price + atr[entry_bar] * params['target']
            
            for j in range(1, 15):
                bar = entry_bar + j
                if bar >= len(l):
                    break
                if l[bar] <= stop_price:
                    trades.append(-atr[entry_bar] * params['stop'] / entry_price - FRICTION)
                    break
                if h[bar] >= target_price:
                    trades.append(atr[entry_bar] * params['target'] / entry_price - FRICTION)
                    break
            else:
                exit_price = c[min(entry_bar + 15, len(c) - 1)]
                trades.append((exit_price - entry_price) / entry_price - FRICTION)
    
    return trades


def calc_stats(trades):
    if len(trades) < 5:
        return {'n': len(trades), 'pf': 0, 'exp': 0, 'wr': 0}
    t = np.array(trades)
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean()*100), 3), 'wr': round(float(len(w)/len(t)*100), 1)}


STRATEGIES = {
    'ADX_BOUNCE': {
        'func': strat_adx_bounce,
        'grid': {
            'adx_max': [20, 25, 30],
            'ema_dist': [1, 2, 3],
            'vol': [1.3, 1.5, 2.0],
            'delay': [1, 2],
            'stop': [0.5, 0.75, 1.0],
            'target': [2.0, 2.5, 3.0],
        },
    },
    'DI_CROSSOVER': {
        'func': strat_di_crossover,
        'grid': {
            'adx_min': [20, 25, 30],
            'vol': [1.3, 1.5],
            'delay': [1, 2],
            'stop': [0.5, 0.75, 1.0],
            'target': [2.0, 2.5, 3.0],
        },
    },
}


print("=" * 100)
print("ADX-BASED STRATEGIES: Trend strength as primary filter (NOT RSI)")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 100)

results = {}

for strat_name, strat_config in STRATEGIES.items():
    print(f"\n{'=' * 100}")
    print(f"STRATEGY: {strat_name}")
    print(f"{'=' * 100}")
    
    print(f"\n{'Pair':<8} {'Train N':<10} {'Train Exp':<12} {'Test N':<10} {'Test Exp':<12} {'Val N':<10} {'Val Exp':<12} {'Verdict'}")
    print("-" * 110)
    
    strat_results = []
    
    for pair in PAIRS:
        df = load_data(pair)
        n = len(df)
        train_end = int(n * 0.6)
        test_end = int(n * 0.8)
        
        ind = compute_indicators(df)
        
        # Grid search
        keys = list(strat_config['grid'].keys())
        values = list(strat_config['grid'].values())
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
            ind_train = {k: v[:train_end] if isinstance(v, np.ndarray) and len(v) == n else v for k, v in ind.items()}
            trades = strat_config['func'](ind_train, params)
            stats = calc_stats(trades)
            if stats['n'] >= 5 and stats['exp'] > best_exp:
                best_exp = stats['exp']
                best_params = params
        
        if best_params is None:
            print(f"{pair:<8} NO VALID PARAMS")
            continue
        
        # Test periods
        ind_train = {k: v[:train_end] if isinstance(v, np.ndarray) and len(v) == n else v for k, v in ind.items()}
        ind_test = {k: v[train_end:test_end] if isinstance(v, np.ndarray) and len(v) == n else v for k, v in ind.items()}
        ind_val = {k: v[test_end:] if isinstance(v, np.ndarray) and len(v) == n else v for k, v in ind.items()}
        
        train_trades = strat_config['func'](ind_train, best_params)
        test_trades = strat_config['func'](ind_test, best_params)
        val_trades = strat_config['func'](ind_val, best_params)
        
        train_stats = calc_stats(train_trades)
        test_stats = calc_stats(test_trades)
        val_stats = calc_stats(val_trades)
        
        profitable_count = sum([
            train_stats['exp'] > 0 and train_stats['n'] >= 3,
            test_stats['exp'] >= 0 and test_stats['n'] >= 2,
            val_stats['exp'] >= 0 and val_stats['n'] >= 2,
        ])
        
        is_valid = profitable_count >= 2 and val_stats['n'] >= 2 and val_stats['exp'] >= 0
        
        if is_valid:
            verdict = "VALID"
            strat_results.append({'pair': pair, 'exp': val_stats['exp'], 'pf': val_stats['pf'], 'n': val_stats['n']})
        else:
            verdict = "WEAK"
        
        print(f"{pair:<8} "
              f"{train_stats['n']:<4} {train_stats['exp']:>7.2f}%   "
              f"{test_stats['n']:<4} {test_stats['exp']:>7.2f}%   "
              f"{val_stats['n']:<4} {val_stats['exp']:>7.2f}%   "
              f"{verdict}")
    
    results[strat_name] = strat_results
    if strat_results:
        print(f"\n  SUMMARY: {len(strat_results)} valid pairs, Avg Exp={np.mean([r['exp'] for r in strat_results]):.2f}%")

# Final summary
print(f"\n{'=' * 100}")
print("ALL STRATEGIES RANKED (by valid pairs and expectancy)")
print(f"{'=' * 100}")
