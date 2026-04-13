"""
Volume Profile Strategy
========================
Completely RSI/BB-free. Uses ONLY volume and price action.
May provide true diversification.
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
    
    # Volume metrics
    vol_sma20 = pd.Series(v).rolling(20).mean().values
    vol_sma50 = pd.Series(v).rolling(50).mean().values
    vol_ratio20 = v / vol_sma20
    vol_ratio50 = v / vol_sma50
    
    # Volume SMA crossover (volume momentum)
    vol_ema8 = pd.Series(v).ewm(span=8, adjust=False).mean().values
    vol_ema21 = pd.Series(v).ewm(span=21, adjust=False).mean().values
    
    # Price relative to recent range
    high_20 = pd.Series(h).rolling(20).max().values
    low_20 = pd.Series(l).rolling(20).min().values
    range_position = (c - low_20) / (high_20 - low_20 + 1e-10)  # 0 = at 20d low, 1 = at 20d high
    
    # Candle patterns
    body = abs(c - o)
    upper_wick = h - np.maximum(c, o)
    lower_wick = np.minimum(c, o) - l
    total_range = h - l + 1e-10
    
    hammer = (lower_wick > 2 * body) & (upper_wick < body * 0.5)  # Long lower wick
    shooting_star = (upper_wick > 2 * body) & (lower_wick < body * 0.5)  # Long upper wick
    
    return {
        'c': c, 'o': o, 'h': h, 'l': l, 'v': v,
        'atr': atr,
        'vol_ratio20': vol_ratio20, 'vol_ratio50': vol_ratio50,
        'vol_ema8': vol_ema8, 'vol_ema21': vol_ema21,
        'range_pos': range_position,
        'hammer': hammer.astype(float),
        'shooting_star': shooting_star.astype(float),
    }


def strat_volume_climax(ind, params):
    """
    VOLUME CLIMAX REVERSAL:
    Extreme volume at price extremes -> reversal
    """
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    atr = ind['atr']
    vol_ratio = ind['vol_ratio20']
    range_pos = ind['range_pos']
    hammer = ind['hammer']
    
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(atr[i]) or np.isnan(vol_ratio[i]) or np.isnan(range_pos[i]):
            continue
        
        # Cap down volume climax: Very high volume + at 20d low + hammer candle
        if (vol_ratio[i] > params['vol'] and 
            range_pos[i] < params['range_low'] and
            (hammer[i] > 0.5 or params['no_pattern'] == 1)):
            
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


def strat_range_bounce(ind, params):
    """
    RANGE BOUNCE: Trade bounces at support/resistance
    Price at 20d low, high volume -> bounce
    """
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    atr = ind['atr']
    vol_ratio = ind['vol_ratio20']
    range_pos = ind['range_pos']
    
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(atr[i]) or np.isnan(vol_ratio[i]) or np.isnan(range_pos[i]):
            continue
        
        # At support (20d low area) with volume
        if (range_pos[i] < params['range_low'] and 
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


def strat_vol_momentum(ind, params):
    """
    VOLUME MOMENTUM: Trade with volume direction
    Vol EMA8 > Vol EMA21 (volume increasing) + price near low -> bounce
    """
    c, o, h, l = ind['c'], ind['o'], ind['h'], ind['l']
    atr = ind['atr']
    vol_ema8 = ind['vol_ema8']
    vol_ema21 = ind['vol_ema21']
    range_pos = ind['range_pos']
    
    trades = []
    for i in range(100, len(c) - 15):
        if np.isnan(atr[i]) or np.isnan(vol_ema8[i]) or np.isnan(vol_ema21[i]):
            continue
        
        # Volume accelerating + price near low
        if (vol_ema8[i] > vol_ema21[i] * params['vol_ratio'] and
            range_pos[i] < params['range_low']):
            
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
    'VOL_CLIMAX': {
        'func': strat_volume_climax,
        'grid': {
            'vol': [2.0, 2.5, 3.0],
            'range_low': [0.1, 0.15, 0.2],
            'no_pattern': [0, 1],
            'delay': [1, 2],
            'stop': [0.5, 0.75, 1.0],
            'target': [2.0, 2.5, 3.0],
        },
    },
    'RANGE_BOUNCE': {
        'func': strat_range_bounce,
        'grid': {
            'range_low': [0.1, 0.15, 0.2],
            'vol': [1.5, 2.0, 2.5],
            'delay': [1, 2],
            'stop': [0.5, 0.75, 1.0],
            'target': [2.0, 2.5, 3.0],
        },
    },
    'VOL_MOMENTUM': {
        'func': strat_vol_momentum,
        'grid': {
            'vol_ratio': [1.2, 1.5, 2.0],
            'range_low': [0.2, 0.3, 0.4],
            'delay': [1, 2],
            'stop': [0.5, 0.75, 1.0],
            'target': [2.0, 2.5, 3.0],
        },
    },
}


print("=" * 100)
print("VOLUME PROFILE STRATEGIES: RSI/BB-free, true diversification test")
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
        
        # Grid search on train
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
            
            ind_train = {k: v[:train_end] if isinstance(v, np.ndarray) and len(v) == n else v 
                         for k, v in ind.items()}
            trades = strat_config['func'](ind_train, params)
            
            stats = calc_stats(trades)
            if stats['n'] >= 5 and stats['exp'] > best_exp:
                best_exp = stats['exp']
                best_params = params
        
        if best_params is None:
            print(f"{pair:<8} NO VALID PARAMS")
            continue
        
        # Test on all periods
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

# Summary
print(f"\n{'=' * 100}")
print("VOLUME STRATEGY SUMMARY")
print(f"{'=' * 100}")

for name, res in results.items():
    print(f"\n{name}: {len(res)} valid pairs")
    if res:
        for r in res:
            print(f"  {r['pair']}: Exp={r['exp']:.2f}%, PF={r['pf']}, N={r['n']}")
