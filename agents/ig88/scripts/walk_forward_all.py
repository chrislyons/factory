"""
Walk-Forward: Test All Strategies for True Diversification
============================================================
Finds strategies with LOW correlation to MR (different entry triggers).
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
    return pd.read_parquet(DATA_DIR / f'binance_{pair}_USDT_240m.parquet')


def compute_all_indicators(df):
    c = df['close'].values
    h = df['high'].values
    l = df['low'].values
    o = df['open'].values
    v = df['volume'].values
    
    # RSI
    delta = df['close'].diff()
    gain = delta.clip(lower=0).ewm(com=13, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, min_periods=14).mean()
    rsi = np.where(loss > 0, 100 - (100 / (1 + gain / loss)), 50)
    
    # Bollinger Bands
    sma20 = df['close'].rolling(20).mean().values
    std20 = df['close'].rolling(20).std().values
    bb_lower = sma20 - std20 * 2
    
    # ATR
    tr = np.maximum(h - l, np.maximum(np.abs(h - np.roll(c, 1)), np.abs(l - np.roll(c, 1))))
    atr = pd.Series(tr).rolling(14).mean().values
    
    # Stochastic
    low_14 = pd.Series(l).rolling(14).min().values
    high_14 = pd.Series(h).rolling(14).max().values
    stoch_k = 100 * (c - low_14) / (high_14 - low_14 + 1e-10)
    stoch_d = pd.Series(stoch_k).rolling(3).mean().values
    
    # MFI
    tp = (h + l + c) / 3
    tp_diff = np.diff(tp, prepend=tp[0])
    mf_pos = np.where(tp_diff > 0, tp * v, 0)
    mf_neg = np.where(tp_diff <= 0, tp * v, 0)
    mf_ratio = pd.Series(mf_pos).rolling(14).sum() / (pd.Series(mf_neg).rolling(14).sum() + 1e-10)
    mfi = (100 - (100 / (1 + mf_ratio))).values
    
    # Volume
    vol_sma = pd.Series(v).rolling(20).mean().values
    vol_ratio = v / vol_sma
    
    return {
        'c': c, 'o': o, 'h': h, 'l': l, 'v': v,
        'rsi': rsi, 'bb_lower': bb_lower, 'atr': atr,
        'stoch_k': stoch_k, 'stoch_d': stoch_d,
        'mfi': mfi, 'vol_ratio': vol_ratio,
    }


def run_strategy(c, o, h, l, ind, strat_name, params, friction):
    """Run a specific strategy."""
    trades = []
    
    if strat_name == 'MR':
        rsi, bb_lower, atr, vol_ratio = ind['rsi'], ind['bb_lower'], ind['atr'], ind['vol_ratio']
        for i in range(100, len(c) - 15):
            if np.isnan(rsi[i]) or np.isnan(bb_lower[i]): continue
            if rsi[i] < params['rsi'] and c[i] < bb_lower[i] and vol_ratio[i] > params['vol']:
                entry_bar = i + 2
                if entry_bar >= len(c) - 15: continue
                entry_price = o[entry_bar]
                stop_price = entry_price - atr[entry_bar] * params['stop']
                target_price = entry_price + atr[entry_bar] * params['target']
                for j in range(1, 15):
                    bar = entry_bar + j
                    if bar >= len(l): break
                    if l[bar] <= stop_price:
                        trades.append(-atr[entry_bar] * params['stop'] / entry_price - friction)
                        break
                    if h[bar] >= target_price:
                        trades.append(atr[entry_bar] * params['target'] / entry_price - friction)
                        break
                else:
                    exit_price = c[min(entry_bar + 15, len(c) - 1)]
                    trades.append((exit_price - entry_price) / entry_price - friction)
    
    elif strat_name == 'STOCH':
        stoch_k, stoch_d, atr, vol_ratio = ind['stoch_k'], ind['stoch_d'], ind['atr'], ind['vol_ratio']
        for i in range(100, len(c) - 15):
            if np.isnan(stoch_k[i]) or np.isnan(stoch_d[i]): continue
            # Stochastic swing failure: K crosses above D while both oversold
            if (stoch_k[i] < params['stoch_oversold'] and 
                stoch_d[i] < params['stoch_oversold'] and
                stoch_k[i] > stoch_d[i] and
                stoch_k[i-1] <= stoch_d[i-1] and
                vol_ratio[i] > params['vol']):
                entry_bar = i + params['delay']
                if entry_bar >= len(c) - 15: continue
                entry_price = o[entry_bar]
                stop_price = entry_price - atr[entry_bar] * params['stop']
                target_price = entry_price + atr[entry_bar] * params['target']
                for j in range(1, 15):
                    bar = entry_bar + j
                    if bar >= len(l): break
                    if l[bar] <= stop_price:
                        trades.append(-atr[entry_bar] * params['stop'] / entry_price - friction)
                        break
                    if h[bar] >= target_price:
                        trades.append(atr[entry_bar] * params['target'] / entry_price - friction)
                        break
                else:
                    exit_price = c[min(entry_bar + 15, len(c) - 1)]
                    trades.append((exit_price - entry_price) / entry_price - friction)
    
    elif strat_name == 'MFI':
        mfi, atr, vol_ratio = ind['mfi'], ind['atr'], ind['vol_ratio']
        for i in range(100, len(c) - 15):
            if np.isnan(mfi[i]): continue
            if mfi[i] < params['mfi_oversold'] and vol_ratio[i] > params['vol']:
                entry_bar = i + params['delay']
                if entry_bar >= len(c) - 15: continue
                entry_price = o[entry_bar]
                stop_price = entry_price - atr[entry_bar] * params['stop']
                target_price = entry_price + atr[entry_bar] * params['target']
                for j in range(1, 15):
                    bar = entry_bar + j
                    if bar >= len(l): break
                    if l[bar] <= stop_price:
                        trades.append(-atr[entry_bar] * params['stop'] / entry_price - friction)
                        break
                    if h[bar] >= target_price:
                        trades.append(atr[entry_bar] * params['target'] / entry_price - friction)
                        break
                else:
                    exit_price = c[min(entry_bar + 15, len(c) - 1)]
                    trades.append((exit_price - entry_price) / entry_price - friction)
    
    return trades


# Parameter grids
STRATEGIES = {
    'STOCH': {
        'grid': {
            'stoch_oversold': [15, 20, 25],
            'vol': [1.3, 1.5, 2.0],
            'delay': [1, 2],
            'stop': [0.5, 0.75, 1.0],
            'target': [2.0, 2.5, 3.0],
        },
    },
    'MFI': {
        'grid': {
            'mfi_oversold': [15, 20, 25],
            'vol': [1.3, 1.5, 2.0],
            'delay': [1, 2],
            'stop': [0.5, 0.75, 1.0],
            'target': [2.0, 2.5, 3.0],
        },
    },
}


def calc_stats(trades):
    if len(trades) < 3:
        return {'n': len(trades), 'pf': 0, 'exp': 0, 'wr': 0}
    t = np.array(trades)
    w = t[t > 0]
    ls = t[t <= 0]
    pf = w.sum() / abs(ls.sum()) if len(ls) > 0 and ls.sum() != 0 else 999
    return {'n': len(t), 'pf': round(float(pf), 2), 'exp': round(float(t.mean()*100), 3), 'wr': round(float(len(w)/len(t)*100), 1)}


print("=" * 120)
print("WALK-FORWARD: Testing Stochastic and MFI for true diversification vs MR")
print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 120)

results = {}

for strat_name, strat_config in STRATEGIES.items():
    print(f"\n{'=' * 120}")
    print(f"STRATEGY: {strat_name}")
    print(f"{'=' * 120}")
    
    print(f"\n{'Pair':<8} {'Train N':<10} {'Train Exp':<12} {'Test N':<10} {'Test Exp':<12} {'Val N':<10} {'Val Exp':<12} {'Verdict'}")
    print("-" * 110)
    
    strat_results = []
    
    for pair in PAIRS:
        df = load_data(pair)
        if df is None:
            print(f"{pair:<8} NO DATA")
            continue
        
        n = len(df)
        train_end = int(n * 0.6)
        test_end = int(n * 0.8)
        
        ind = compute_all_indicators(df)
        
        # Grid search on train
        keys = list(strat_config['grid'].keys())
        values = list(strat_config['grid'].values())
        all_combos = list(product(*values))
        
        np.random.seed(42)
        sample_size = min(100, len(all_combos))
        if len(all_combos) > sample_size:
            indices = np.random.choice(len(all_combos), sample_size, replace=False)
            combos = [all_combos[i] for i in indices]
        else:
            combos = all_combos
        
        best_params = None
        best_exp = -999
        
        for combo in combos:
            params = dict(zip(keys, combo))
            
            trades = run_strategy(
                c=df['close'].values[:train_end],
                o=df['open'].values[:train_end],
                h=df['high'].values[:train_end],
                l=df['low'].values[:train_end],
                ind={k: v[:train_end] if isinstance(v, np.ndarray) and len(v) == len(df) else v 
                     for k, v in ind.items()},
                strat_name=strat_name,
                params=params,
                friction=FRICTION
            )
            
            stats = calc_stats(trades)
            if stats['n'] >= 5 and stats['exp'] > best_exp:
                best_exp = stats['exp']
                best_params = params
        
        if best_params is None:
            print(f"{pair:<8} NO VALID PARAMS")
            continue
        
        # Test on all periods
        train_trades = run_strategy(
            df['close'].values[:train_end], df['open'].values[:train_end],
            df['high'].values[:train_end], df['low'].values[:train_end],
            {k: v[:train_end] if isinstance(v, np.ndarray) and len(v) == len(df) else v for k, v in ind.items()},
            strat_name, best_params, FRICTION
        )
        
        test_trades = run_strategy(
            df['close'].values[train_end:test_end], df['open'].values[train_end:test_end],
            df['high'].values[train_end:test_end], df['low'].values[train_end:test_end],
            {k: v[train_end:test_end] if isinstance(v, np.ndarray) and len(v) == len(df) else v for k, v in ind.items()},
            strat_name, best_params, FRICTION
        )
        
        val_trades = run_strategy(
            df['close'].values[test_end:], df['open'].values[test_end:],
            df['high'].values[test_end:], df['low'].values[test_end:],
            {k: v[test_end:] if isinstance(v, np.ndarray) and len(v) == len(df) else v for k, v in ind.items()},
            strat_name, best_params, FRICTION
        )
        
        train_stats = calc_stats(train_trades)
        test_stats = calc_stats(test_trades)
        val_stats = calc_stats(val_trades)
        
        profitable_count = sum([
            train_stats['exp'] > 0 and train_stats['n'] >= 3,
            test_stats['exp'] > 0 and test_stats['n'] >= 1,
            val_stats['exp'] > 0 and val_stats['n'] >= 1,
        ])
        
        is_valid = profitable_count >= 2 and val_stats['n'] >= 2 and val_stats['exp'] > 0
        
        if is_valid:
            verdict = "VALID"
            strat_results.append({
                'pair': pair, 'exp': val_stats['exp'], 'pf': val_stats['pf'], 
                'n': val_stats['n'], 'wr': val_stats['wr'], 'params': best_params
            })
        else:
            verdict = "WEAK"
        
        print(f"{pair:<8} "
              f"{train_stats['n']:<4} {train_stats['exp']:>7.2f}%   "
              f"{test_stats['n']:<4} {test_stats['exp']:>7.2f}%   "
              f"{val_stats['n']:<4} {val_stats['exp']:>7.2f}%   "
              f"{verdict}")
    
    results[strat_name] = strat_results

# Summary
print(f"\n{'=' * 120}")
print("WALK-FORWARD SUMMARY")
print(f"{'=' * 120}")

for strat_name, strat_results in results.items():
    print(f"\n{strat_name}: {len(strat_results)} valid pairs")
    if strat_results:
        avg_exp = np.mean([r['exp'] for r in strat_results])
        total_trades = sum([r['n'] for r in strat_results])
        print(f"  Average Exp: {avg_exp:.2f}%, Total trades: {total_trades}")
        for r in strat_results:
            print(f"  {r['pair']}: Exp={r['exp']:.2f}%, PF={r['pf']}, N={r['n']}")
